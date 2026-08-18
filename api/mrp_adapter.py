"""
api/mrp_adapter.py — Explosão de Materiais via API Excia.
Usa BuscarFichaTecnicaProduto + Estoque para gerar o MRP de um pedido.
Insumos 'a caminho' via OrdemTinturaria quando disponíveis.
OrdemMalharia: endpoint retornou vazio na investigação de 13/08/2026 — desativado com aviso.
OrdemCompra: endpoint retorna ordens gerais de compra (não itens de insumo de produção) — desativado.
"""

from .excia_client import ExciaAPIClient
from engine.models import LinhaPedido, BlocoInsumo, ProdutoMRP
from typing import List, Dict, Optional
from datetime import datetime


# Mapeamento de código de setor → nome da fase (baseado em config/setores.yaml)
# Usado para preencher a fase de consumo do insumo a partir do campo 'setor' da ficha técnica
_SETOR_PARA_FASE: Dict[str, str] = {
    "00": "PCP",
    "38": "EMBALAGEM",
    "28": "REVISAO",
    "18": "REVISAO",       # PRE_REVISAO
    "20": "COSTURA",
    "10": "COSTURA",       # PRE_COSTURA
    "30": "QUAL_COSTURA",
    "03": "CORTE",
    "84": "CORTE",         # CD_CORTE
    "01": "ENCAIXE",
    "70": "ENCAIXE",       # AGUARDANDO_ENCAIXE
    "22": "ESTAMPARIA_NUCA",
    "23": "ESTAMPARIA_NUCA",
    "12": "ESTAMPARIA_NUCA",  # PRE_ESTAMPARIA
    "32": "QUAL_ESTAMPARIA",
    "130": "QUAL_COSTURA",  # CONTROLE_QUALIDADE (tratamos como qualidade)
    "41": "PCP",            # DESENVOLVIMENTO
}


class MrpAdapter:
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()

    def explodir_necessidades(
        self,
        pedido_linhas: List[LinhaPedido],
        data_inicio_busca: str = "01/01/2026",
    ) -> List[BlocoInsumo]:
        """
        Recebe as linhas do pedido e gera a explosão de materiais via API.
        Para cada linha:
          1. Busca BuscarFichaTecnicaProduto → insumos + setor de consumo
          2. Busca Estoque por insumo+cor → saldo físico atual
          3. Busca OrdemTinturaria → malha/ribana 'a caminho' (em kg)
        Retorna lista de BlocoInsumo pronta para o engine/matching.py.
        """
        insumos_agrupados: Dict[str, BlocoInsumo] = {}

        # ── Passo 1: Coletar insumos e cores de todas as linhas ───────────
        chaves_necessarias: set = set()
        materiais_necessarios: set = set()

        for linha in pedido_linhas:
            ficha = self.client.get(
                "BuscarFichaTecnicaProduto", params={"codigo": linha.codigo}
            )
            if not ficha or not isinstance(ficha, list) or len(ficha) == 0:
                continue

            linha._ficha_cache = ficha  # type: ignore[attr-defined]

            for ins_data in ficha[0].get("insumos", []):
                cod_insumo = ins_data.get("insumo", "")
                if not cod_insumo:
                    continue

                # Validar se o insumo é aplicável à grade deste pedido
                qtde_aplicavel = _calcular_qtde_aplicavel(ins_data, linha)
                if qtde_aplicavel <= 0:
                    continue

                materiais_necessarios.add(cod_insumo)

                # Determinar cor do insumo para esta variante de cor do produto
                cod_cor_insumo = _resolver_cor_insumo(ins_data, linha.cor)
                if cod_cor_insumo is not None:
                    chaves_necessarias.add(f"{cod_insumo}_{cod_cor_insumo}")

        # ── Passo 2: Buscar estoques e ordens futuras em paralelo ─────────
        estoque_dict = self._obter_estoque(list(chaves_necessarias))
        materiais_dict = self._obter_dicionario_materiais(list(materiais_necessarios))
        tinturaria_dict = self._obter_ordens_tinturaria(data_inicio_busca)

        # ── Passo 3: Montar os BlocoInsumo ───────────────────────────────
        for linha in pedido_linhas:
            ficha = getattr(linha, "_ficha_cache", None)
            if not ficha:
                continue

            artigo_data = ficha[0]
            for ins_data in artigo_data.get("insumos", []):
                cod_insumo = ins_data.get("insumo", "")
                if not cod_insumo:
                    continue

                # Validar se o insumo é aplicável à grade deste pedido
                qtde_aplicavel = _calcular_qtde_aplicavel(ins_data, linha)
                if qtde_aplicavel <= 0:
                    continue

                # Resolver cor
                cod_cor_insumo = _resolver_cor_insumo(ins_data, linha.cor)
                if cod_cor_insumo is None:
                    continue

                chave = f"{cod_insumo}_{cod_cor_insumo}"

                # Consumo: consumo_unitário × quantidade_aplicável_da_grade
                consumo_un = float(ins_data.get("consumo", 0.0))
                consumo_total = consumo_un * qtde_aplicavel

                # Setor de consumo: usar o campo real da ficha técnica
                setor_codigo = str(ins_data.get("setor", ""))
                fase_consumo = _SETOR_PARA_FASE.get(setor_codigo, "CORTE")

                # Saldo dos estoques/ordens
                estoque_qtd = estoque_dict.get(chave, 0.0)
                tinturaria_qtd = tinturaria_dict.get(chave, 0.0)
                desc_insumo = materiais_dict.get(cod_insumo, "MATERIAL NÃO ENCONTRADO")

                if chave not in insumos_agrupados:
                    bloco = BlocoInsumo(
                        cod_insumo=cod_insumo,
                        descricao=desc_insumo,
                        un="UN",
                        cod_cor=cod_cor_insumo,
                        nome_cor="",
                        consumo=0.0,
                        estoque=estoque_qtd,
                        compra=0.0,          # OrdemCompra não tem itens de insumo de produção
                        tecelagem=0.0,       # OrdemMalharia retornou vazio — desativado
                        pend_tint=tinturaria_qtd,
                        tinturaria=0.0,
                        saldo=0.0,
                    )
                    insumos_agrupados[chave] = bloco

                bloco = insumos_agrupados[chave]
                bloco.consumo += consumo_total
                bloco.saldo = (
                    bloco.estoque + bloco.compra + bloco.tecelagem
                    + bloco.pend_tint + bloco.tinturaria - bloco.consumo
                )

                # Número de OF vinculado à linha (se disponível via _of_numero)
                of_num = getattr(linha, "_of_numero", "")

                prod = ProdutoMRP(
                    of=of_num,
                    cod_artigo=linha.codigo,
                    descricao=linha.descricao,
                    setor_atual=fase_consumo,
                    consumo=consumo_total,
                    aloc_estoque=bloco.estoque,
                    aloc_compra=bloco.compra,
                    aloc_tecelagem=bloco.tecelagem,
                    aloc_pend_tint=bloco.pend_tint,
                    aloc_tinturaria=bloco.tinturaria,
                    saldo=bloco.saldo,
                )
                bloco.produtos.append(prod)

        return list(insumos_agrupados.values())

    # ── Métodos privados de busca ─────────────────────────────────────────

    def _obter_estoque(self, chaves_necessarias: List[str]) -> Dict[str, float]:
        """Estoque físico atual por (cod_insumo, cod_cor)."""
        from concurrent.futures import ThreadPoolExecutor

        estoque_dict: Dict[str, float] = {}

        def fetch(chave: str):
            partes = chave.split("_", 1)
            if len(partes) != 2:
                return []
            cod, cor = partes
            try:
                resp = self.client.get(
                    "Estoque", params={"codigo": cod, "tipo": "M", "cor": cor}
                )
                return resp if isinstance(resp, list) else []
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=10) as executor:
            for resp in executor.map(fetch, chaves_necessarias):
                for item in resp:
                    cod_item = item.get("codigo", "")
                    cor_item = item.get("cor", "")
                    qtd = float(item.get("quantidade", 0.0))
                    k = f"{cod_item}_{cor_item}"
                    estoque_dict[k] = estoque_dict.get(k, 0.0) + qtd

        return estoque_dict

    def _obter_dicionario_materiais(self, codigos: List[str]) -> Dict[str, str]:
        """Descrição de cada material pelo código."""
        from concurrent.futures import ThreadPoolExecutor

        materiais_dict: Dict[str, str] = {}

        def fetch(cod: str):
            try:
                resp = self.client.get("MaterialLista", params={"codigo": cod})
                if isinstance(resp, list) and len(resp) > 0:
                    return cod, resp[0].get("descricao", "SEM DESCRICAO")
            except Exception:
                pass
            return cod, "SEM DESCRICAO"

        with ThreadPoolExecutor(max_workers=10) as executor:
            for cod, desc in executor.map(fetch, codigos):
                materiais_dict[cod] = desc

        return materiais_dict

    def _obter_ordens_tinturaria(self, data_str: str) -> Dict[str, float]:
        """
        Ordens de Tinturaria abertas: malha/ribana 'a caminho' (em kg).
        Chave: '{cod_insumo}_{cod_cor}'.
        Campo 'peso_liquido' é em kg — mesma unidade que o Estoque de malha.
        Campo 'ficha' estava vazio na investigação de 13/08/2026 (sem vínculo OP confirmado).
        Tratamos como estoque futuro agregado (pend_tint).
        """
        tinturaria_dict: Dict[str, float] = {}
        try:
            resp = self.client.get("OrdemTinturaria", params={"dats": data_str})
            if isinstance(resp, list):
                for ordem in resp:
                    for item in ordem.get("itens", []):
                        cod = item.get("codigo", "")
                        cor = item.get("cor", "")
                        # Só conta ordens ativas
                        if item.get("situacao", "") not in ("A", ""):
                            continue
                        qtd = float(item.get("peso_liquido", 0.0))
                        if cod and qtd > 0:
                            chave = f"{cod}_{cor}"
                            tinturaria_dict[chave] = tinturaria_dict.get(chave, 0.0) + qtd
        except Exception:
            pass
        return tinturaria_dict


# ── Funções auxiliares ────────────────────────────────────────────────────────

def _resolver_cor_insumo(ins_data: dict, cor_produto: str) -> Optional[str]:
    """
    Determina o código de cor do insumo para uma dada cor de produto.
    Lógica:
      1. Procura na lista 'cor' do insumo o item onde cor == cor_produto
         e retorna cor_i (código interno da cor do insumo).
      2. Se não encontrar, usa o primeiro item da lista (fallback).
      3. Se a lista estiver vazia, retorna None (insumo sem cor — ignorar).

    Campo 'cor_i' = "0" significa que o insumo não tem variação de cor
    (ex: linha de costura preta usada para qualquer cor de produto).
    """
    cor_lista = ins_data.get("cor", [])
    if not cor_lista:
        return None

    # Busca exata pela cor do produto
    for c in cor_lista:
        if c.get("cor") == cor_produto:
            return c.get("cor_i", "0")

    # Fallback: primeira cor disponível
    return cor_lista[0].get("cor_i", "0")


# Conjunto padrão de tamanhos/grades de vestuário conhecidos
_TAMANHOS_CONHECIDOS = {
    "RN", "PP", "P", "M", "G", "GG", "XG", "XGG", "EG", "EGG", "XXG",
    "G1", "G2", "G3", "G4", "U", "UN", "UNICO",
    "1", "2", "3", "4", "5", "6", "7", "8", "10", "12", "14", "16", "18",
    "01", "02", "03", "04", "05", "06", "07", "08"
}


def _calcular_qtde_aplicavel(ins_data: dict, linha: LinhaPedido) -> float:
    """
    Calcula a quantidade de peças da linha às quais o insumo se aplica.
    Regra do campo 'faixa' na Ficha Técnica do Excia:
      - Faixas genéricas / siglas de cliente ('00', '', '0', 'RIA', 'REN', 'YOU', 'TODOS', etc.):
        aplicam-se a toda a produção do produto -> linha.qtde_total.
      - Tamanho específico ('PP', 'P', 'M', 'G', 'GG', '2', '4', etc.):
        aplica-se SOMENTE se aquele tamanho existir na grade do pedido (linha.grade).
        Se for um tamanho conhecido mas não existir no pedido, retorna 0.0 (insumo não utilizado).
    """
    faixa = str(ins_data.get("faixa", "")).strip().upper()

    # 1. Faixas vazias ou explicitamente genéricas -> quantidade total
    if not faixa or faixa in ("00", "0", "TODOS", "GERAL", "PADRAO", "LIVRE"):
        return float(linha.qtde_total)

    if not linha.grade:
        return float(linha.qtde_total)

    grade_norm = {str(k).strip().upper(): float(v) for k, v in linha.grade.items()}

    # 2. Correspondência direta de tamanho (ex: faixa "PP" == grade "PP", ou faixa "2" == grade "2")
    if faixa in grade_norm:
        return grade_norm[faixa]

    # 3. Correspondência numérica (ex: faixa "04" == grade "4")
    if faixa.isdigit():
        f_int = int(faixa)
        for k, v in grade_norm.items():
            if k.isdigit() and int(k) == f_int:
                return v

    # 4. Se a faixa for um tamanho conhecido de grade (mas não está na grade deste pedido):
    #    Ex: Pedido só tem "PP" ou "2", e o insumo tem faixa "P", "M", "3", "4"
    #    -> Insumo não é consumido neste pedido.
    if faixa in _TAMANHOS_CONHECIDOS or (faixa.isdigit() and int(faixa) <= 50):
        return 0.0

    # 5. Caso contrário, trata-se de sigla de cliente/grade (ex: "RIA", "REN", "YOU", "CEA")
    #    -> Aplica-se a toda a produção do pedido.
    return float(linha.qtde_total)



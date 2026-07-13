"""
parsers/mrp_parser.py — Parser do PDF "Relatório de Consumos - Detalhado".

Estratégia REVISADA após análise do PDF real:
- O extract_text() gera linhas bem formadas para as linhas de insumo e produto
- O problema de "colunas coladas" ocorre em alguns campos da linha de insumo
  (ex: "11.460,00064.415,00") mas podemos usar extract_words() POR LINHA para separar
- Usamos extract_text() para identificar o tipo de linha e extract_words() para os números

Layout observado:
  Linha de insumo (8 dígitos): "03044079 RIBANA... KG 021180 - PRETO ... 34,614 18,650 0,000 0,000 0,000 107,100 91,136"
  Linha de produto (OF=6 dígitos): "263920 1104019 VESTIDO DIANA NEW PRETO 2637 00 - PCP 34,614 18,650 0,000 15,964 0,000"

Reconciliação:
  Saldo = Estoque + Compra + Tecelagem + PendTint + Tinturaria - Consumo (tolerância 0,01)
  Consumo agregado == soma dos consumos dos produtos (tolerância 0,01)
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

from engine.models import BlocoInsumo, ProdutoMRP
from parsers.comum import parse_num_br


# Regex para identificar tipo de linha
_RE_INSUMO_AGR = re.compile(r"^\d{8}\b")   # cod_insumo = 8 dígitos no início
_RE_PRODUTO = re.compile(r"^\d{6}\s+\d{7}")  # OF(6) + artigo(7)

# Tolerância de reconciliação
_TOL_RECONCIL = 0.05

# Nomes das 7 colunas numéricas em ordem
COLUNAS_ORDEM = ["Consumo", "Estoque", "Compra", "Tecelagem", "PendTint", "Tinturaria", "Saldo"]


def parse_mrp(pdf_bytes: bytes) -> list[BlocoInsumo]:
    """
    Extrai todos os blocos de insumo do PDF MRP.
    Usa extração por texto por linha com separação numérica por coordenadas.
    """
    # Extrair todas as linhas do PDF com palavras e coordenadas
    linhas_estruturadas = _extrair_linhas_com_coords(pdf_bytes)

    blocos: list[BlocoInsumo] = []
    bloco_atual: Optional[dict] = None
    colunas_x: dict[str, tuple[float, float]] = {}

    for linha_info in linhas_estruturadas:
        texto = linha_info["texto"]
        words = linha_info["words"]

        # Detectar cabeçalho de colunas
        if _e_cabecalho_colunas(texto):
            colunas_x = _extrair_x_colunas_cabecalho(words)
            continue

        # Linha de insumo agregado (8 dígitos no início)
        if _RE_INSUMO_AGR.match(texto):
            if bloco_atual:
                blocos.append(_finalizar_bloco(bloco_atual))
            bloco_atual = _parse_linha_insumo(texto, linha_info, colunas_x)
            continue

        # Linha de produto (OF 6 dígitos + artigo 7 dígitos)
        if _RE_PRODUTO.match(texto) and bloco_atual is not None:
            prod = _parse_linha_produto(texto, linha_info, colunas_x)
            if prod:
                bloco_atual["produtos"].append(prod)
            continue

    # Finalizar último bloco
    if bloco_atual:
        blocos.append(_finalizar_bloco(bloco_atual))

    # Reconciliação
    for bloco in blocos:
        _reconciliar(bloco)

    return blocos


def _extrair_linhas_com_coords(pdf_bytes: bytes) -> list[dict]:
    """
    Extrai linhas do PDF com texto e palavras com coordenadas.
    Agrupa palavras por Y (top) e constrói representação por linha.
    """
    linhas_result = []
    TOL_Y = 3.0

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=2,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            if not words:
                continue

            # Agrupar palavras por linha (top similar)
            grupos: list[list[dict]] = []
            grupo_atual: list[dict] = [words[0]]
            top_ref = words[0]["top"]

            for w in words[1:]:
                if abs(w["top"] - top_ref) <= TOL_Y:
                    grupo_atual.append(w)
                else:
                    grupos.append(sorted(grupo_atual, key=lambda x: x["x0"]))
                    grupo_atual = [w]
                    top_ref = w["top"]
            if grupo_atual:
                grupos.append(sorted(grupo_atual, key=lambda x: x["x0"]))

            chars = page.chars

            for grupo in grupos:
                texto = " ".join(w["text"] for w in grupo)
                # Associar caracteres a esta linha
                top_min = min(w["top"] for w in grupo) - 2.0
                bot_max = max(w["bottom"] for w in grupo) + 2.0
                chars_linha = [c for c in chars if top_min <= c["top"] <= bot_max]
                
                linhas_result.append({
                    "texto": texto,
                    "words": grupo,
                    "chars": chars_linha
                })

    return linhas_result


def _e_cabecalho_colunas(texto: str) -> bool:
    """Verifica se a linha é o cabeçalho de colunas do MRP."""
    t = texto.lower()
    return "consumo" in t and "estoque" in t and "saldo" in t


def _extrair_x_colunas_cabecalho(words: list[dict]) -> dict[str, tuple[float, float]]:
    """
    Mapeia colunas numéricas pelo cabeçalho.
    Usa x0 de cada token como limite esquerdo da coluna.
    O limite direito = x0 da próxima coluna - 1px.
    
    Trata casos especiais:
    - 'CompraTecelage' colado → divide por posição proporcional
    - 'Pend.' + 'Tint.' → dois tokens formando 'PendTint'
    """
    # Lista de (nome_coluna, x0_inicio) — usando x0 como fronteira esquerda
    colunas: list[tuple[str, float]] = []
    visto: set[str] = set()
    pend_w: Optional[dict] = None  # token 'Pend.' aguardando 'Tint.'

    for w in words:
        texto_lower = w["text"].lower().strip(".")
        x0 = w["x0"]
        x1 = w["x1"]

        # Tratar "CompraTecelage" colado
        if "compra" in texto_lower and "tecelage" in texto_lower:
            largura = x1 - x0
            x0_compra = x0
            x0_tecel = x0 + largura * 0.5  # divide ao meio pelo x0
            if "Compra" not in visto:
                colunas.append(("Compra", x0_compra))
                visto.add("Compra")
            if "Tecelagem" not in visto:
                colunas.append(("Tecelagem", x0_tecel))
                visto.add("Tecelagem")
            continue

        # "Pend." → aguardar "Tint."
        if texto_lower in ("pend", "pend."):
            pend_w = w
            continue

        # "Tint." → completar "Pend. Tint."
        if texto_lower in ("tint", "tint.") and pend_w is not None:
            if "PendTint" not in visto:
                colunas.append(("PendTint", pend_w["x0"]))
                visto.add("PendTint")
            pend_w = None
            continue

        # Mapeamento direto
        MAPA = {
            "consumo": "Consumo",
            "estoque": "Estoque",
            "tinturaria": "Tinturaria",
            "saldo": "Saldo",
        }
        for alias, nome in MAPA.items():
            if alias in texto_lower and nome not in visto:
                colunas.append((nome, x0))
                visto.add(nome)
                break

    # Ordenar por x0
    colunas.sort(key=lambda c: c[1])

    # Construir intervalos: [x0_desta, x0_próxima - 1]
    mapa: dict[str, tuple[float, float]] = {}
    for i, (nome, x0_col) in enumerate(colunas):
        x_max = colunas[i + 1][1] - 1 if i + 1 < len(colunas) else 10000
        mapa[nome] = (x0_col - 5, x_max)  # -5px de margem à esquerda

    return mapa


def _extrair_numeros_por_coluna(linha_info: dict, colunas_x: dict) -> dict[str, float]:
    """
    Extrai os números de uma linha atribuindo cada um à coluna por posição X.
    Se não houver mapa de colunas, extrai todos os números em ordem.
    Usa um fallback com regex caso haja números colados.
    """
    resultado: dict[str, float] = {c: 0.0 for c in COLUNAS_ORDEM}
    words = linha_info.get("words", [])

    if not colunas_x:
        # Sem mapa de colunas — extrair números em ordem e mapear sequencialmente
        nums = _extrair_todos_numeros(words)
        for i, (nome_col, val) in enumerate(zip(COLUNAS_ORDEM, nums)):
            resultado[nome_col] = val
        return resultado

    colunas_ordenadas = sorted(colunas_x.items(), key=lambda kv: kv[1][0])

    for w in words:
        txt = w.get("text", "")
        if not _e_numero_br(txt):
            continue
        x_centro = (w["x0"] + w["x1"]) / 2
        for i, (nome, (x_min, x_max)) in enumerate(colunas_ordenadas):
            if x_min <= x_centro <= x_max:
                try:
                    resultado[nome] = parse_num_br(txt)
                except ValueError:
                    # Fallback para string colada
                    separados = _desambiguar_numeros_colados(txt)
                    for j, s in enumerate(separados):
                        idx_col = i + j
                        if idx_col < len(colunas_ordenadas):
                            nome_col = colunas_ordenadas[idx_col][0]
                            try:
                                resultado[nome_col] = parse_num_br(s)
                            except ValueError:
                                pass
                break

    return resultado


def _desambiguar_numeros_colados(texto: str) -> list[str]:
    """
    Tenta separar números aglutinados pelo parser (ex: '11.460,00064.415,000').
    Procura blocos terminados em ,XX ou ,XXX.
    """
    matches = re.finditer(r'([\d.]+(?:,\d{2,3}))', texto)
    return [m.group(1) for m in matches]


def _extrair_todos_numeros(words: list[dict]) -> list[float]:
    """Extrai todos os números de uma linha em ordem."""
    nums = []
    for w in words:
        if _e_numero_br(w["text"]):
            try:
                nums.append(parse_num_br(w["text"]))
            except ValueError:
                separados = _desambiguar_numeros_colados(w["text"])
                for s in separados:
                    try:
                        nums.append(parse_num_br(s))
                    except ValueError:
                        pass
    return nums


def _e_numero_br(s: str) -> bool:
    """Verifica se a string parece um número no formato BR."""
    s = s.strip()
    return bool(re.match(r"^[\d.,]+$", s) and any(c.isdigit() for c in s))


def _parse_linha_insumo(texto: str, linha_info: dict, colunas_x: dict) -> dict:
    """
    Parseia uma linha de insumo agregado.
    Formato: "XXXXXXXX DESCRICAO... UN COD_COR - NOME_COR ... N1 N2 N3 N4 N5 N6 N7"
    """
    # Separar código do insumo (primeiros 8 dígitos)
    m = re.match(r"(\d{8})\s+(.+)", texto)
    if not m:
        return _bloco_vazio(texto[:8] if len(texto) >= 8 else texto)

    cod_insumo = m.group(1)
    resto = m.group(2)

    # Tentar extrair: descrição, UN, cod_cor, nome_cor
    # Padrão: DESCRICAO UN COD_COR - NOME_COR [numeros adicionais de lote]
    # UN: 2-3 letras maiúsculas
    # COD_COR: 6 dígitos (ou 5)
    un = ""
    cod_cor = ""
    nome_cor = ""
    descricao = resto

    # Tentar extrair cod_cor (6 dígitos) e nome_cor
    m_cor = re.search(r"\b(\d{5,6})\s*[-–]\s*([A-Z][A-Z\s]+?)(?=\s+\d|\s+[A-Z]{1,3}\s|\s*$)", resto, re.IGNORECASE)
    if m_cor:
        antes = resto[:m_cor.start()].strip()
        cod_cor = m_cor.group(1)
        nome_cor = m_cor.group(2).strip()

        # UN: última palavra antes do cod_cor que seja 2-3 letras maiúsculas
        partes_antes = antes.split()
        if partes_antes and re.match(r"^[A-Z]{1,3}$", partes_antes[-1]):
            un = partes_antes[-1]
            descricao = " ".join(partes_antes[:-1])
        else:
            descricao = antes
    else:
        # Extrair UN e descrição simples
        partes = resto.split()
        # Procurar UN por posição (geralmente antes do código de cor)
        for i, p in enumerate(partes):
            if re.match(r"^[A-Z]{1,3}$", p) and i > 0:
                un = p
                descricao = " ".join(partes[:i])
                break
        if not un:
            descricao = resto

    # Extrair números por coluna via bucketing de chars
    nums = _extrair_numeros_por_coluna(linha_info, colunas_x)

    return {
        "cod_insumo": cod_insumo,
        "descricao": descricao.strip(),
        "un": un,
        "cod_cor": cod_cor,
        "nome_cor": nome_cor,
        "consumo": nums["Consumo"],
        "estoque": nums["Estoque"],
        "compra": nums["Compra"],
        "tecelagem": nums["Tecelagem"],
        "pend_tint": nums["PendTint"],
        "tinturaria": nums["Tinturaria"],
        "saldo": nums["Saldo"],
        "produtos": [],
    }


def _parse_linha_produto(texto: str, linha_info: dict, colunas_x: dict) -> Optional[dict]:
    """
    Parseia uma linha de produto (OF).
    Formato: "XXXXXX YYYYYYY DESCRICAO AASS SS - SETOR N1 N2 N3 N4 N5"
    OF = 6 dígitos, artigo = 7 dígitos
    """
    m = re.match(r"(\d{6})\s+(\d{7})\s+(.+)", texto)
    if not m:
        return None

    of = m.group(1)
    cod_artigo = m.group(2)
    resto = m.group(3)

    # Extrair setor: padrão "AASS SS - NOME_SETOR" — pode ter números depois (nas células do produto)
    # Ex: "VESTIDO DIANA NEW PRETO 2637 00 - PCP 34,614 18,650..."
    # Ex: "PIJAMA ADULTO MASCULINO VISCO MARINHO 2637 20 - COSTURA 1.726,000..."
    setor_atual = ""
    descricao_prod = resto

    # Regex: AASS(4 dígitos) + setor_cod(1-3 dígitos) + ' - ' + setor_nome (só letras)
    # O setor_nome para antes de números ou fim de string
    m_setor = re.search(
        r"\b(\d{4})\s+(\d{1,3})\s*[-–]\s*([A-Z][A-Z/_.\s]*?)(?=\s+[\d,.]|\s*$)",
        resto, re.IGNORECASE
    )
    if m_setor:
        setor_cod = m_setor.group(2).strip()
        setor_nome = m_setor.group(3).strip()
        setor_atual = f"{setor_cod} - {setor_nome}"
        descricao_prod = resto[:m_setor.start()].strip()

    # Extrair números por coluna via bucketing
    nums = _extrair_numeros_por_coluna(linha_info, colunas_x)

    return {
        "of": of,
        "cod_artigo": cod_artigo,
        "descricao": descricao_prod,
        "setor_atual": setor_atual,
        "consumo": nums["Consumo"],
        "aloc_estoque": nums["Estoque"],
        "aloc_compra": nums["Compra"],
        "aloc_tecelagem": nums["Tecelagem"],
        "aloc_pend_tint": nums["PendTint"],
        "aloc_tinturaria": nums["Tinturaria"],
        "saldo": nums["Saldo"],
    }


def _finalizar_bloco(dados: dict) -> BlocoInsumo:
    produtos = [
        ProdutoMRP(
            of=p["of"],
            cod_artigo=p["cod_artigo"],
            descricao=p["descricao"],
            setor_atual=p["setor_atual"],
            consumo=p["consumo"],
            aloc_estoque=p["aloc_estoque"],
            aloc_compra=p["aloc_compra"],
            aloc_tecelagem=p["aloc_tecelagem"],
            aloc_pend_tint=p["aloc_pend_tint"],
            aloc_tinturaria=p["aloc_tinturaria"],
            saldo=p["saldo"],
        )
        for p in dados.get("produtos", [])
    ]
    return BlocoInsumo(
        cod_insumo=dados["cod_insumo"],
        descricao=dados["descricao"],
        un=dados.get("un", ""),
        cod_cor=dados.get("cod_cor", ""),
        nome_cor=dados.get("nome_cor", ""),
        consumo=dados["consumo"],
        estoque=dados["estoque"],
        compra=dados["compra"],
        tecelagem=dados["tecelagem"],
        pend_tint=dados["pend_tint"],
        tinturaria=dados["tinturaria"],
        saldo=dados["saldo"],
        produtos=produtos,
    )


def _bloco_vazio(cod: str) -> dict:
    return {
        "cod_insumo": cod,
        "descricao": "",
        "un": "",
        "cod_cor": "",
        "nome_cor": "",
        "consumo": 0.0,
        "estoque": 0.0,
        "compra": 0.0,
        "tecelagem": 0.0,
        "pend_tint": 0.0,
        "tinturaria": 0.0,
        "saldo": 0.0,
        "produtos": [],
    }


def _reconciliar(bloco: BlocoInsumo) -> None:
    """
    Reconciliação obrigatória (seção 5.2 do ROADMAP):
    1. Saldo == Estoque + Compra + Tecelagem + PendTint + Tinturaria - Consumo
    2. Consumo agregado == soma dos consumos dos produtos
    """
    avisos = []

    # Reconciliação 1: fórmula do Saldo
    saldo_calc = (
        bloco.estoque + bloco.compra + bloco.tecelagem +
        bloco.pend_tint + bloco.tinturaria - bloco.consumo
    )
    if abs(saldo_calc - bloco.saldo) > _TOL_RECONCIL:
        avisos.append(
            f"⚠️ ERRO DE SALDO: o sistema calculou {saldo_calc:.3f} mas o PDF reporta {bloco.saldo:.3f} "
            f"(dif={abs(saldo_calc - bloco.saldo):.3f})"
        )

    # Reconciliação 2: consumo total == soma produtos
    if bloco.produtos:
        soma_prod = sum(p.consumo for p in bloco.produtos)
        if abs(soma_prod - bloco.consumo) > _TOL_RECONCIL:
            avisos.append(
                f"⚠️ ATENÇÃO: a soma dos produtos ({soma_prod:.3f}) diverge do consumo total lido ({bloco.consumo:.3f})"
            )

    if avisos:
        bloco.parse_ok = False
        bloco.avisos_reconciliacao = avisos

"""
engine/matching.py — Ligação Pedido ↔ produtos do MRP (seção 3.7 do ROADMAP).
Chave primária: código do artigo.
Validação de quantidade com buffer +7%.
"""

from __future__ import annotations

from typing import Optional

from engine.models import (
    BlocoInsumo,
    LinhaPedido,
    MatchInsumo,
    MatchPedido,
    ProdutoMRP,
)
from parsers.comum import arredondar


def casar_com_mrp(
    linha: LinhaPedido,
    mrp: list[BlocoInsumo],
    cfg: dict,
) -> MatchPedido:
    """
    Encontra os insumos do MRP correspondentes a uma linha de pedido.
    Conforme seção 3.7: chave = código do artigo; valida quantidade; trata divergência de cor.
    """
    artigo = linha.artigo
    qtd_of = arredondar(linha.qtde_total * (1 + cfg["geral"]["buffer_producao_pct"] / 100),
                        cfg["geral"]["arredondamento"])
    tol_pct = cfg["geral"]["tolerancia_match_qtd_pct"] / 100

    avisos: list[str] = []
    insumos: list[MatchInsumo] = []
    of_match: str = ""
    confianca = "BAIXA"

    # Encontrar todos os produtos do MRP com este artigo
    produtos_encontrados: list[tuple[ProdutoMRP, BlocoInsumo]] = []
    for bloco in mrp:
        for prod in bloco.produtos:
            if prod.cod_artigo == artigo:
                produtos_encontrados.append((prod, bloco))

    if not produtos_encontrados:
        return MatchPedido(
            cod_artigo=artigo,
            of="",
            confianca="BAIXA",
            insumos=[],
            avisos=[
                f"Artigo {artigo} não encontrado no MRP — gere o Relatório de Consumos "
                f"incluindo a OF deste pedido e reenvie"
            ],
            tecido_principal_encontrado=False,
        )

    # Agrupar por OF (um artigo pode ter várias OFs)
    ofs_por_artigo: dict[str, list[tuple[ProdutoMRP, BlocoInsumo]]] = {}
    for prod, bloco in produtos_encontrados:
        ofs_por_artigo.setdefault(prod.of, []).append((prod, bloco))

    # Escolher a OF que melhor bate na quantidade
    melhor_of = None
    melhor_score = -1

    for of_num, prod_list in ofs_por_artigo.items():
        # A quantidade de peças da OF no MRP é o consumo máximo entre todos os seus insumos
        # (os aviamentos medidos em UN indicam a quantidade de peças, enquanto tecidos em KG dão valores baixos)
        consumo_max = max(p.consumo for p, _ in prod_list)
        diff_rel = abs(consumo_max - qtd_of) / max(qtd_of, 1)

        # Verificar se bate: qtd_MRP ≈ qtd_OF (tolerância)
        if diff_rel <= tol_pct:
            score = 1.0 - diff_rel
            if score > melhor_score:
                melhor_score = score
                melhor_of = of_num
                confianca = "ALTA"
        # Consumo dobrado (pijama/conjuntos): ~ 2x qtd_OF
        elif abs(consumo_max - 2 * qtd_of) / max(qtd_of, 1) <= tol_pct:
            avisos.append(
                f"Consumo do MRP ({consumo_max:.0f}) ~ 2x qtd OF ({qtd_of}) "
                f"— possível conjunto/2 peças"
            )
            score = 0.5
            if score > melhor_score:
                melhor_score = score
                melhor_of = of_num
                confianca = "MEDIA"

    # Se nenhuma OF bateu na quantidade, usar a primeira encontrada com aviso
    if melhor_of is None:
        melhor_of = next(iter(ofs_por_artigo))
        # Pegar o consumo máximo para exibir no aviso
        consumo_max = max(p.consumo for p, _ in ofs_por_artigo[melhor_of])
        avisos.append(
            f"Quantidade da OF no MRP ({consumo_max:.0f}) não confere com qtd do pedido "
            f"(pedido×1,07={qtd_of}) — verificar no Excia"
        )
        confianca = "BAIXA"

    of_match = melhor_of
    prod_list = ofs_por_artigo[of_match]

    # Verificar divergência de cor
    for prod, bloco in prod_list:
        if bloco.cod_cor and linha.cod_cor and bloco.cod_cor != linha.cod_cor:
            avisos.append(
                f"Divergência de código de cor: pedido ({linha.cod_cor} {linha.nome_cor}) "
                f"vs MRP ({bloco.cod_cor} {bloco.nome_cor}) — confirmar de-para de cores no Excia"
            )
            break  # Uma mensagem por OF é suficiente

    # Construir lista de insumos
    tecido_principal_encontrado = False
    keywords_tecido = cfg.get("tecido_principal_keywords", ["MALHA", "RIBANA"])

    for prod, bloco in prod_list:
        # Verificar se é tecido principal
        desc_upper = bloco.descricao.upper()
        for kw in keywords_tecido:
            if kw in desc_upper:
                tecido_principal_encontrado = True
                break

        is_cor_divergente = False
        if bloco.cod_cor and linha.cod_cor and bloco.cod_cor != linha.cod_cor:
            is_cor_divergente = True

        insumo = MatchInsumo(
            cod_insumo=bloco.cod_insumo,
            descricao=bloco.descricao,
            un=bloco.un,
            cod_cor=bloco.cod_cor,
            nome_cor=bloco.nome_cor,
            necessario=prod.consumo,
            aloc_estoque=prod.aloc_estoque,
            aloc_compra=prod.aloc_compra,
            aloc_tecelagem=prod.aloc_tecelagem,
            aloc_pend_tint=prod.aloc_pend_tint,
            aloc_tinturaria=prod.aloc_tinturaria,
            saldo=prod.saldo,
            cor_divergente=is_cor_divergente,
        )
        insumos.append(insumo)

    if not tecido_principal_encontrado:
        avisos.append(
            "Tecido principal (MALHA/RIBANA) não localizado no MRP para este produto — "
            "análise de malha incompleta, verificar no Excia"
        )

    return MatchPedido(
        cod_artigo=artigo,
        of=of_match,
        confianca=confianca,
        insumos=insumos,
        avisos=avisos,
        tecido_principal_encontrado=tecido_principal_encontrado,
    )

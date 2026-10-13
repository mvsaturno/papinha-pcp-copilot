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
    codigo = linha.codigo
    qtd_of = arredondar(linha.qtde_total * (1 + cfg["geral"]["buffer_producao_pct"] / 100),
                        cfg["geral"]["arredondamento"])
    tol_pct = cfg["geral"]["tolerancia_match_qtd_pct"] / 100

    avisos: list[str] = []
    insumos: list[MatchInsumo] = []
    of_match: str = ""
    confianca = "BAIXA"

    # Encontrar todos os produtos do MRP com este artigo
    produtos_encontrados: list[tuple[ProdutoMRP, BlocoInsumo]] = []
    total_produtos_mrp = 0
    
    for bloco in mrp:
        total_produtos_mrp += len(bloco.produtos)
        for prod in bloco.produtos:
            if prod.cod_artigo == codigo:
                produtos_encontrados.append((prod, bloco))

    # FALLBACK: Se o MRP não tiver NENHUM produto detalhado (é o PPCP Textil / Resumido)
    # tentamos casar os insumos pela cor do pedido
    is_resumo = (total_produtos_mrp == 0 and len(mrp) > 0)

    if not produtos_encontrados and not is_resumo:
        return MatchPedido(
            cod_artigo=codigo,
            of="",
            confianca="BAIXA",
            insumos=[],
            avisos=[
                f"Artigo {codigo} não encontrado no MRP — gere o Relatório de Consumos "
                f"incluindo a OF deste pedido e reenvie"
            ],
            tecido_principal_encontrado=False,
        )

    # Se for um resumo, faremos uma lógica dedicada
    if is_resumo:
        return _casar_com_mrp_resumido(linha, mrp, cfg)

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
        buffer_pct = cfg["geral"]["buffer_producao_pct"]
        avisos.append(
            f"Quantidade da OF no MRP ({consumo_max:.0f}) não confere com qtd do pedido "
            f"(pedido×{1 + buffer_pct/100:.0%}={qtd_of}) — verificar no Excia"
        )
        confianca = "BAIXA"

    of_match = melhor_of
    prod_list = ofs_por_artigo[of_match]

    # Detectar se os blocos vêm da integração de API
    vem_da_api = any(getattr(b, "origem_api", False) or getattr(p, "origem_api", False) for p, b in prod_list)

    # Verificar divergência de cor (apenas para relatório PDF, pois via API os domínios de cores são distintos)
    if not vem_da_api:
        for prod, bloco in prod_list:
            if bloco.cod_cor and linha.cor and bloco.cod_cor != linha.cor:
                avisos.append(
                    f"Divergência de código de cor: pedido ({linha.cor} {linha.desc_cor}) "
                    f"vs MRP ({bloco.cod_cor} {bloco.nome_cor}) — confirmar de-para de cores no Excia"
                )
                break  # Uma mensagem por OF é suficiente

    # Construir lista de insumos agrupando por (cod_insumo, cod_cor) para somar consumos de partes/faixas
    tecido_principal_encontrado = False
    keywords_tecido = cfg.get("tecido_principal_keywords", ["MALHA", "RIBANA"])

    itens_agrupados: dict[tuple[str, str], dict] = {}
    for prod, bloco in prod_list:
        chave = (bloco.cod_insumo, bloco.cod_cor)
        if chave not in itens_agrupados:
            itens_agrupados[chave] = {
                "bloco": bloco,
                "prod": prod,
                "consumo_total": 0.0,
                "cor_fallback": False,
                "setor_atual": prod.setor_atual if prod.setor_atual else "",
            }
        itens_agrupados[chave]["consumo_total"] += prod.consumo
        if getattr(prod, "cor_fallback", False) or getattr(bloco, "cor_fallback", False):
            itens_agrupados[chave]["cor_fallback"] = True
        if prod.setor_atual and not itens_agrupados[chave]["setor_atual"]:
            itens_agrupados[chave]["setor_atual"] = prod.setor_atual

    for (cod_ins, cod_cor), item in itens_agrupados.items():
        bloco = item["bloco"]
        prod = item["prod"]
        consumo_total = item["consumo_total"]
        cor_fallback = item["cor_fallback"]
        setor_atual = item["setor_atual"]

        desc_upper = bloco.descricao.upper()
        for kw in keywords_tecido:
            if kw in desc_upper:
                tecido_principal_encontrado = True
                break

        insumo_avisos: list[str] = []
        is_cor_divergente = False

        if vem_da_api:
            # Via API, cor divergente só ocorre se não encontrou a cor na ficha e caiu no fallback
            if cor_fallback:
                is_cor_divergente = True
                insumo_avisos.append(
                    f"cor {linha.cor} não cadastrada na ficha deste insumo (usando {bloco.cod_cor})"
                )
        else:
            # Caminho legado PDF: comparação direta de código de cor
            ignorar_divergencia = False
            cor_nome_up = bloco.nome_cor.upper() if bloco.nome_cor else ""
            if bloco.cod_cor in ["", "0", "00", "000000", "00000", "0000", "000", "00"] or "PADRAO" in cor_nome_up or "UNICO" in cor_nome_up:
                ignorar_divergencia = True

            if not ignorar_divergencia:
                if bloco.cod_cor and linha.cor and bloco.cod_cor != linha.cor:
                    is_cor_divergente = True

        insumo = MatchInsumo(
            cod_insumo=bloco.cod_insumo,
            descricao=bloco.descricao,
            un=bloco.un,
            cod_cor=bloco.cod_cor,
            nome_cor=bloco.nome_cor,
            necessario=consumo_total,
            aloc_estoque=bloco.estoque if vem_da_api else prod.aloc_estoque,
            aloc_compra=bloco.compra if vem_da_api else prod.aloc_compra,
            aloc_tecelagem=bloco.tecelagem if vem_da_api else prod.aloc_tecelagem,
            aloc_pend_tint=bloco.pend_tint if vem_da_api else prod.aloc_pend_tint,
            aloc_tinturaria=bloco.tinturaria if vem_da_api else prod.aloc_tinturaria,
            saldo=bloco.saldo if vem_da_api else prod.saldo,
            cor_divergente=is_cor_divergente,
            avisos=insumo_avisos,
            fase_consumo=setor_atual,
            estoque_cru=getattr(bloco, "estoque_cru", 0.0),
            cascata_info=getattr(bloco, "cascata_info", None),
        )
        insumos.append(insumo)

    if not tecido_principal_encontrado:
        avisos.append(
            "Tecido principal (MALHA/RIBANA) não localizado no MRP para este produto — "
            "análise de malha incompleta, verificar no Excia"
        )

    return MatchPedido(
        cod_artigo=codigo,
        of=of_match,
        confianca=confianca,
        insumos=insumos,
        avisos=avisos,
        tecido_principal_encontrado=tecido_principal_encontrado,
    )


def _casar_com_mrp_resumido(linha: LinhaPedido, mrp: list[BlocoInsumo], cfg: dict) -> MatchPedido:
    """
    Lógica de fallback quando o MRP anexado é o 'PPCP Textil' (sem OFs detalhadas).
    Assumimos que o MRP foi gerado *filtrado* para a OF deste pedido.
    Filtramos os insumos pela cor da linha atual (ou sem cor/UNICO).
    """
    insumos: list[MatchInsumo] = []
    avisos = [
        "⚠️ Relatório resumido ('PPCP Textil') detectado. "
        "Os insumos foram vinculados de forma agregada ao pedido, "
        "sem distinção por OF ou Artigo."
    ]
    
    tecido_principal_encontrado = False
    keywords_tecido = cfg.get("tecido_principal_keywords", ["MALHA", "RIBANA"])

    for bloco in mrp:
        # Verificar match de cor:
        # Se o bloco tem uma cor definida (diferente de 'UNICO' ou '0')
        # e é diferente da cor da linha, pulamos (não pertence a essa variante de cor)
        is_unico = bloco.cod_cor == "0" or bloco.nome_cor == "UNICO" or not bloco.cod_cor
        if not is_unico and linha.cor and bloco.cod_cor != linha.cor:
            continue

        desc_upper = bloco.descricao.upper()
        for kw in keywords_tecido:
            if kw in desc_upper:
                tecido_principal_encontrado = True
                break

        insumo = MatchInsumo(
            cod_insumo=bloco.cod_insumo,
            descricao=bloco.descricao,
            un=bloco.un,
            cod_cor=bloco.cod_cor,
            nome_cor=bloco.nome_cor,
            necessario=bloco.consumo, # Usa o consumo total do bloco
            aloc_estoque=bloco.estoque,
            aloc_compra=bloco.compra,
            aloc_tecelagem=bloco.tecelagem,
            aloc_pend_tint=bloco.pend_tint,
            aloc_tinturaria=bloco.tinturaria,
            saldo=bloco.saldo,
            cor_divergente=False, # Como não temos OF específica, não marcamos divergência aqui
        )
        insumos.append(insumo)

    return MatchPedido(
        cod_artigo=linha.codigo,
        of="Múltiplas" if len(insumos) > 0 else "",
        confianca="MEDIA",
        insumos=insumos,
        avisos=avisos,
        tecido_principal_encontrado=tecido_principal_encontrado,
    )

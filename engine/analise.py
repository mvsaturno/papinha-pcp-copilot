"""
engine/analise.py — Orquestrador principal da análise PCP (seção 6 do ROADMAP).
Executa matching, cronograma, insumos, capacidade e gera veredito por pedido.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from typing import Optional

from engine.models import (
    BlocoInsumo,
    CapacidadeSemanal,
    CardPedido,
    LinhaPedido,
    MatchInsumo,
    MatchPedido,
    Pedido,
    ResultadoAnalise,
)
from engine.matching import casar_com_mrp
from engine.cronograma import montar_cronograma, ajustar_cronograma_backward
from engine.insumos import avaliar_insumos
from engine.capacidade import alertas_globais_capacidade, verificar_capacidade_pedido
from parsers.comum import (
    arredondar,
    formatar_data_br,
    semana_aass,
    sexta_da_semana,
    quarta_da_semana,
    aass_add,
)


def analisar(
    pedidos: list[Pedido],
    mrp: list[BlocoInsumo],
    cap: CapacidadeSemanal,
    hoje: date,
    cfg: dict,
    resultado: Optional[ResultadoAnalise] = None,
) -> ResultadoAnalise:
    """
    Orquestrador principal (pseudocódigo da seção 6 do ROADMAP).
    Recebe pedidos + MRP + capacidade + config → ResultadoAnalise completo.
    """
    if resultado is None:
        resultado = ResultadoAnalise(
            timestamp=hoje.isoformat(),
            data_analise=hoje,
        )

    # ── Alertas globais de capacidade ─────────────────────────────────────
    resultado.alertas_globais = alertas_globais_capacidade(cap, hoje, cfg)

    # ── Análise por pedido ────────────────────────────────────────────────
    cards = []

    for pedido in pedidos:
        for linha in pedido.linhas:
            card = _analisar_linha(pedido, linha, mrp, cap, hoje, cfg)
            cards.append(card)

    resultado.pedidos = cards
    return resultado


def _analisar_linha(
    pedido: Pedido,
    linha: LinhaPedido,
    mrp: list[BlocoInsumo],
    cap: CapacidadeSemanal,
    hoje: date,
    cfg: dict,
) -> CardPedido:
    """Analisa uma linha de pedido e gera o card de resultado."""
    buffer_pct = cfg["geral"]["buffer_producao_pct"]
    arr_modo = cfg["geral"]["arredondamento"]
    semanas_antes = cfg["geral"]["semanas_antes_entrega_cliente"]
    horizonte_dias = cfg["geral"].get("horizonte_sinalizacao_dias", 90)

    # 1. Matching com MRP
    match = casar_com_mrp(linha, mrp, cfg)

    # Se a linha já tiver dados de OF emitida via API, propaga para match
    of_emitida = getattr(linha, "of_emitida", False) or match.of_emitida
    numero_of = getattr(linha, "numero_of", None) or match.numero_of
    semana_of = getattr(linha, "semana_of_oficial", None) or match.semana_of_oficial
    dt_emissao_of = getattr(linha, "dt_emissao_of", None) or match.dt_emissao_of
    setor_atual_of = getattr(linha, "setor_atual_of", None) or match.setor_atual_of
    qtde_of_oficial = getattr(linha, "qtde_of_oficial", None) or match.qtde_of_oficial

    # Se a OF já foi emitida no Excia, a quantidade da OF é o valor oficial já com quebra
    if of_emitida and qtde_of_oficial:
        qtd_of = int(qtde_of_oficial)
    else:
        qtd_of = arredondar(linha.qtde_total * (1 + buffer_pct / 100), arr_modo)

    # 2. Cronograma draft — se a OF já foi emitida no Excia, inicia na data real da OF
    data_inicio_cronograma = dt_emissao_of if (of_emitida and dt_emissao_of) else hoje
    cronograma = montar_cronograma(linha, match, data_inicio_cronograma, cfg)

    # 3. Avaliação de insumos (usa cronograma para determinar bloqueante)
    insumos_avaliados = avaliar_insumos(match.insumos, cronograma, hoje, cfg)

    # 4. Semana alvo e mínima
    semana_entrega = semana_aass(pedido.entrega)
    # Se a OF já foi emitida, a semana alvo oficial é a semana gravada no Excia
    if of_emitida and semana_of:
        semana_alvo = semana_of
        semana_minima = min(cronograma.semana_fim_aass, semana_of)
    else:
        semana_alvo = _aass_sub(semana_entrega, semanas_antes)
        semana_minima = cronograma.semana_fim_aass

    # 5. Checagem de capacidade
    analise_cap = verificar_capacidade_pedido(qtd_of, semana_alvo, semana_minima, cap, cfg)

    # 5.5 Ajustar cronograma para backward scheduling
    if of_emitida and semana_of:
        # No Excia, o cronograma da OF é ancorado na semana gravada na ordem (término na quarta-feira)
        fim_producao = quarta_da_semana(semana_of)
        cronograma = ajustar_cronograma_backward(cronograma, fim_producao)
        semana_minima = cronograma.semana_fim_aass
    else:
        estrategia = cfg["geral"].get("estrategia_cronograma", "jit")
        if estrategia == "jit" and analise_cap.semana_sugerida is not None:
            fim_producao = sexta_da_semana(analise_cap.semana_sugerida)
            cronograma = ajustar_cronograma_backward(cronograma, fim_producao)
            if analise_cap.cabe_no_alvo and cronograma.inicio_mais_tarde and cronograma.inicio_mais_tarde >= hoje:
                semana_minima = min(semana_minima, analise_cap.semana_sugerida)

    # 6. Veredito (seção 3.8 do Sprint 2)
    veredito, motivos, sugestao, semana_sug = _decidir_veredito(
        pedido, linha, match, cronograma, insumos_avaliados, analise_cap,
        semana_alvo, semana_minima, qtd_of, cap, cfg
    )

    # Se a OF já foi emitida no Excia, adicionar aviso contextual positivo de rastreamento
    if of_emitida and numero_of:
        motivos.insert(0, f"🏷️ Ordem de Produção OF {numero_of} emitida no Excia (Semana Oficial: {semana_of or semana_alvo}).")

    # 7. Flag horizonte longo
    horizonte_longo = (pedido.entrega - hoje).days > horizonte_dias

    # 8. Flags e avisos consolidados
    flags = list(match.avisos)
    for ins in insumos_avaliados:
        flags.extend(ins.avisos)
    if horizonte_longo:
        pend_alvo = cap.periodos.get(semana_alvo, 0)
        limite = cfg["capacidade"]["limite_total_semana"]
        flags.append(
            f"ℹ️ Horizonte longo (>{horizonte_dias} dias) — capacidade semana {semana_alvo}: "
            f"{pend_alvo}/{limite} peças"
        )

    # Dados brutos para auditoria (<details> na UI)
    dados_brutos = {
        "pedido_numero": pedido.numero,
        "ped_cliente": pedido.ped_cliente,
        "artigo": linha.codigo,
        "descricao": linha.descricao,
        "grade": linha.grade,
        "qtde_total": linha.qtde_total,
        "qtd_of": qtd_of,
        "of_emitida": of_emitida,
        "numero_of": numero_of,
        "semana_of_oficial": semana_of,
        "emissao": formatar_data_br(pedido.emissao),
        "entrega": formatar_data_br(pedido.entrega),
        "semana_entrega_aass": semana_entrega,
        "semana_alvo_aass": semana_alvo,
        "match_of": match.of,
        "match_confianca": match.confianca,
        "rota": cronograma.rota_detectada,
        "pcp_dias": cronograma.pcp_dias,
        "folga_dias": cronograma.folga_dias,
        "inicio_mais_tarde": formatar_data_br(cronograma.inicio_mais_tarde) if cronograma.inicio_mais_tarde else None,
        "avisos_pedido": pedido.avisos_parsing,
    }

    return CardPedido(
        numero_pedido=pedido.numero,
        artigo=linha.codigo,
        descricao=linha.descricao,
        cod_cor=linha.cor,
        nome_cor=linha.desc_cor,
        qtde_pedido=linha.qtde_total,
        qtd_of=qtd_of,
        entrega_cliente=pedido.entrega,
        semana_alvo=semana_alvo,
        veredito=veredito,
        motivos=motivos,
        match=match,
        insumos=insumos_avaliados,
        cronograma=cronograma,
        capacidade=analise_cap,
        sugestao=sugestao,
        sugestao_semana=semana_sug,
        of_emitida=of_emitida,
        numero_of=numero_of,
        semana_of_oficial=semana_of,
        dt_emissao_of=dt_emissao_of,
        setor_atual_of=setor_atual_of,
        qtde_of_oficial=qtde_of_oficial,
        horizonte_longo=horizonte_longo,
        avisos_flags=flags,
        dados_brutos=dados_brutos,
    )


def _decidir_veredito(
    pedido: Pedido,
    linha: LinhaPedido,
    match: MatchPedido,
    cronograma,
    insumos: list[MatchInsumo],
    analise_cap,
    semana_alvo: int,
    semana_minima: int,
    qtd_of: int,
    cap: CapacidadeSemanal,
    cfg: dict,
) -> tuple[str, list[str], str, Optional[int]]:
    """
    Determina veredito, motivos, sugestão e semana sugerida.
    Conforme seção 3.8 do ROADMAP.
    VERDE | AMARELO | VERMELHO
    """
    motivos: list[str] = []
    tem_alertas = False
    tem_bloqueante = False

    # Verificar cronograma
    cronograma_nao_fecha = semana_minima > semana_alvo
    if cronograma_nao_fecha:
        motivos.append(
            f"Cronograma não fecha: produção terminaria na semana {semana_minima}, "
            f"alvo era {semana_alvo}"
        )

    # Verificar capacidade na semana alvo
    cap_estourada = not analise_cap.cabe_no_alvo
    if cap_estourada:
        motivos.extend(analise_cap.avisos)

    # Verificar insumos
    for ins in insumos:
        if ins.status == "FALTA":
            motivos.append(
                f"Insumo em falta: {ins.descricao} — acionar COMPRAS "
                f"(fase: {ins.fase_consumo}, bloqueante: {'Sim' if ins.bloqueante else 'Não'})"
            )
            if ins.bloqueante:
                tem_bloqueante = True
            else:
                tem_alertas = True
        elif ins.status == "OK_FUTURO" and ins.bloqueante:
            motivos.append(
                f"Insumo a caminho mas bloqueante: {ins.descricao} "
                f"(disponível ~{formatar_data_br(ins.disponivel_em) if ins.disponivel_em else '?'}, "
                f"fase: {ins.fase_consumo})"
            )
            tem_bloqueante = True
        elif ins.status == "OK_FUTURO":
            # Não adicionamos o texto aos motivos do topo para evitar poluição/redundância,
            # pois já é listado com data e status na tabela de insumos abaixo.
            tem_alertas = True

    # Avisos de matching → alertas mas não bloqueantes necessariamente
    if match.avisos:
        tem_alertas = True
        for av in match.avisos:
            if av not in motivos:
                motivos.append(av)

    # Sugestão de semana e lógica da janela
    semana_sug = analise_cap.semana_sugerida
    autonomia = cfg["geral"].get("semanas_autonomia_pcp", 3)
    
    # Determinar a "zona" do veredito (Sprint 2)
    semana_cliente = aass_add(semana_alvo, cfg["geral"].get("semanas_antes_entrega_cliente", 2))
    
    if semana_sug is None or semana_sug >= semana_cliente:
        veredito = "VERMELHO"
        if not motivos:
            motivos.append(f"Inviável na data — propor entrega na semana {aass_add(semana_sug or semana_cliente, 2)}")
    else:
        # Está em alguma das zonas candidatas viáveis
        if (semana_alvo - autonomia) <= semana_sug <= semana_alvo:
            # Janela
            veredito = "VERDE"
            if semana_sug < semana_alvo:
                motivos.append(f"Antecipação de {semana_alvo - semana_sug} sem., dentro da autonomia")
        elif semana_alvo < semana_sug < semana_cliente:
            # Extra 2
            veredito = "AMARELO"
            motivos.append("Viável, mas consome a margem interna de segurança (entrega−2) — decisão do PCP")
        else:
            # Extra 1 (antes da janela)
            veredito = "AMARELO"
            motivos.append(f"Viável apenas com antecipação de {semana_alvo - semana_sug} semanas — REQUER AUTORIZAÇÃO DA GESTÃO")
            
        if tem_bloqueante or tem_alertas or match.confianca == "BAIXA":
            if veredito == "VERDE":
                veredito = "AMARELO"  # rebaixado por ressalvas

        if veredito == "VERDE" and not motivos:
            motivos.append(f"Produzir para terminar na semana {semana_sug} (JIT)")

    sugestao = _montar_sugestao(semana_sug, semana_alvo, pedido.entrega, cfg)
    return veredito, motivos, sugestao, semana_sug


def _montar_sugestao(semana_sug: Optional[int], semana_alvo: int, entrega: date, cfg: dict) -> str:
    """Monta a sugestão textual para o analista."""
    if semana_sug is None:
        return "❌ Nenhuma semana viável encontrada no horizonte analisado"

    if semana_sug <= semana_alvo:
        sexta = sexta_da_semana(semana_sug)
        return (
            f"✅ Produzir na semana {semana_sug} "
            f"(termina {formatar_data_br(sexta)}) — "
            f"entrega ao cliente mantida ({formatar_data_br(entrega)})"
        )
    else:
        semana_entrega_nova = aass_add(semana_sug, 1)
        sexta_nova = sexta_da_semana(semana_entrega_nova)
        return (
            f"❌ Data inviável — sugerir ao comercial nova entrega na semana "
            f"{semana_entrega_nova} ({formatar_data_br(sexta_nova)})"
        )


def _aass_sub(aass: int, n: int) -> int:
    """Subtrai n semanas de um AASS."""
    return aass_add(aass, -n)

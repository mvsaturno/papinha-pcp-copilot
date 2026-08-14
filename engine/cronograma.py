"""
engine/cronograma.py — Regra 2: montagem do cronograma draft (seção 3.5 do ROADMAP).
Lead times derivados das OFs reais (Mapa SEM 2637) — DRAFT para validação.
Simplificação documentada: dias corridos, sem feriados/fins de semana.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from engine.models import Cronograma, FaseCronograma, MatchPedido, LinhaPedido
from parsers.comum import semana_aass
from api.fluxo_adapter import FluxoAdapter


def montar_cronograma(
    linha: LinhaPedido,
    match: Optional[MatchPedido],
    hoje: date,
    cfg: dict,
) -> Cronograma:
    """
    Monta o cronograma draft para uma linha de pedido.
    Detecta a rota pelo nome do artigo e calcula datas de cada fase.
    """
    fases_dias = cfg["fases_dias"]
    rotas_cfg = cfg["rotas"]
    overrides_cfg = cfg.get("overrides_fases_por_rota", {})
    lt_futuro = cfg["lead_times_estoque_futuro_dias"]

    # 1. Calcular duração da fase PCP (dinâmica — seção 3.5)
    pcp_dias = _calcular_pcp_dias(match, fases_dias, lt_futuro, cfg)

    # 2. Obter código do fluxo via API ParteProdutoLista
    fluxo_inferido = getattr(linha, "fluxo_id", None)
    fluxo_adapter = FluxoAdapter()
    
    if not fluxo_inferido and linha.codigo:
        try:
            fluxo_inferido = fluxo_adapter.buscar_fluxo_do_produto(linha.codigo)
        except Exception:
            pass

    # 3. Detectar rota dinâmica pela API
    fases_dinamicas = None
    if fluxo_inferido:
        try:
            fases_dinamicas = fluxo_adapter.buscar_fases(fluxo_inferido)
        except Exception:
            pass

    def _obter_dias_fase(nome: str) -> int:
        n = nome.upper().replace("Ã", "A").replace("Ó", "O").replace("É", "E").replace("Á", "A")
        if "PCP" in n:
            return pcp_dias
        if "ENCAIXE" in n and "AGUARDANDO" not in n:
            return fases_dias.get("ENCAIXE", 1)
        if "CORTE" in n and "CD" not in n:
            return fases_dias.get("CORTE", 4)
        if "COSTURA" in n and "QUAL" not in n and "PRE" not in n and "ACAB" not in n:
            return fases_dias.get("COSTURA", 11)
        if "LAVANDERIA" in n or "LAVACAO" in n:
            if "QUAL" in n or "PRE" in n:
                return fases_dias.get("QUAL_LAVANDERIA", 1)
            return fases_dias.get("LAVANDERIA", 10)
        if "APLIQUE" in n:
            if "QUAL" in n or "PRE" in n:
                return fases_dias.get("QUAL_APLIQUE", 1)
            return fases_dias.get("APLIQUE", 8)
        if "ESTAMPARIA" in n or "ESTAMPA" in n:
            if "QUAL" in n or "PRE" in n:
                return fases_dias.get("QUAL_ESTAMPARIA", 1)
            return fases_dias.get("ESTAMPARIA_NUCA", 4)
        if "ACAB" in n:
            return fases_dias.get("ACAB_COST", 4)
        if "PASSADORIA" in n:
            return fases_dias.get("PASSADORIA", 4)
        if "REVISAO" in n:
            return fases_dias.get("REVISAO", 6)
        if "EMBALAGEM" in n:
            return fases_dias.get("EMBALAGEM", 4)
        if "QUAL" in n or "CQ" in n:
            return 1
        return fases_dias.get(nome, 1)

    if fases_dinamicas:
        rota_nome = f"API ({fluxo_inferido})"
        fases_rota = []
        for f_nome in fases_dinamicas:
            d = _obter_dias_fase(f_nome)
            fases_rota.append((f_nome, d))
    else:
        rota_nome = _detectar_rota(linha.descricao, rotas_cfg)
        rota = rotas_cfg.get(rota_nome, rotas_cfg["DEFAULT"])
        overrides = overrides_cfg.get(rota_nome, {})
        
        fases_rota = []
        for nome_fase in rota:
            if nome_fase == "PCP":
                d = pcp_dias
            else:
                d = overrides.get(nome_fase, fases_dias.get(nome_fase, 1))
            fases_rota.append((nome_fase, d))

    # 4. Calcular cronograma
    fases: list[FaseCronograma] = []
    cursor = hoje

    for nome_fase, dias in fases_rota:
        inicio = cursor
        
        # Adicionar dias úteis
        fim = inicio
        dias_add = 0
        while dias_add < dias:
            fim += timedelta(days=1)
            if fim.weekday() < 5:  # seg a sex
                dias_add += 1
                
        fases.append(FaseCronograma(nome=nome_fase, inicio=inicio, fim=fim, dias=dias))
        cursor = fim

    data_fim = cursor
    semana_fim = semana_aass(data_fim)

    return Cronograma(
        fases=fases,
        rota_detectada=rota_nome,
        pcp_dias=pcp_dias,
        data_fim=data_fim,
        semana_fim_aass=semana_fim,
    )


def _detectar_rota(descricao: str, rotas_cfg: dict) -> str:
    """
    Detecta a rota de produção pelo nome do artigo.
    Verifica keywords na ordem de especificidade (mais específico primeiro).
    Fallback: DEFAULT.
    """
    desc_upper = descricao.upper()

    # Ordem: mais específico primeiro
    for chave in ["PIJAMA", "CONJUNTO", "VESTIDO", "REGATA", "CAMISETA"]:
        if chave in desc_upper and chave in rotas_cfg:
            return chave

    return "DEFAULT"


def _calcular_pcp_dias(
    match: Optional[MatchPedido],
    fases_dias: dict,
    lt_futuro: dict,
    cfg: dict,
) -> int:
    """
    Calcula a duração dinâmica da fase PCP (espera pelo tecido principal).
    Conforme seção 3.5:
      - OK_ESTOQUE      → pcp_min (2 dias)
      - Tinturaria/PendTint → lead_tinturaria (14 dias)
      - Tecelagem       → lead_tecelagem + lead_tinturaria (21 dias)
      - FALTA           → lead_compra + lead_tecelagem + lead_tinturaria (28 dias)
      - Não localizado  → pcp_padrao (21 dias) + alerta
    """
    pcp_min = fases_dias.get("PCP_MIN", 2)
    pcp_padrao = fases_dias.get("PCP_PADRAO", 21)

    lt_compra = lt_futuro.get("compra", 7)
    lt_tecelagem = lt_futuro.get("tecelagem", 7)
    lt_tinturaria = lt_futuro.get("tinturaria", 14)

    keywords_tecido = cfg.get("tecido_principal_keywords", ["MALHA", "RIBANA"])

    if match is None or not match.insumos:
        # Sem MRP — usar padrão
        return pcp_padrao

    if not match.tecido_principal_encontrado:
        # Tecido não localizado — usar padrão
        return pcp_padrao

    # Encontrar o insumo de tecido principal
    tecido_insumo = None
    for ins in match.insumos:
        desc_upper = ins.descricao.upper()
        for kw in keywords_tecido:
            if kw in desc_upper:
                tecido_insumo = ins
                break
        if tecido_insumo:
            break

    if tecido_insumo is None:
        return pcp_padrao

    status = tecido_insumo.status

    if status == "OK_ESTOQUE":
        return pcp_min

    if status == "OK_FUTURO":
        # Descobrir de qual coluna vem
        if tecido_insumo.aloc_tinturaria > 0 or tecido_insumo.aloc_pend_tint > 0:
            return lt_tinturaria  # 14 dias
        if tecido_insumo.aloc_tecelagem > 0:
            return lt_tecelagem + lt_tinturaria  # 7 + 14 = 21 dias
        if tecido_insumo.aloc_compra > 0:
            return lt_compra + lt_tecelagem + lt_tinturaria  # 7 + 7 + 14 = 28 dias
        return pcp_padrao

    if status == "FALTA":
        return lt_compra + lt_tecelagem + lt_tinturaria  # 28 dias

    return pcp_padrao


def ajustar_cronograma_backward(crono: Cronograma, nova_data_fim: date) -> Cronograma:
    """
    Recalcula as datas do cronograma de trás para a frente para que termine na nova_data_fim.
    Mantém as durações originais das fases (apenas dias úteis).
    """
    if not crono.fases:
        return crono

    dias_folga = (nova_data_fim - crono.data_fim).days
    
    novas_fases = []
    cursor = nova_data_fim
    
    for f in reversed(crono.fases):
        fim = cursor
        inicio = fim
        dias_sub = 0
        while dias_sub < f.dias:
            inicio -= timedelta(days=1)
            if inicio.weekday() < 5:  # seg a sex
                dias_sub += 1
                
        novas_fases.append(FaseCronograma(
            nome=f.nome,
            inicio=inicio,
            fim=fim,
            dias=f.dias
        ))
        cursor = inicio

    novas_fases.reverse()

    crono.fases = novas_fases
    crono.data_fim = nova_data_fim
    crono.semana_fim_aass = semana_aass(nova_data_fim)
    crono.folga_dias = dias_folga
    crono.inicio_mais_tarde = novas_fases[0].inicio if novas_fases else None

    return crono

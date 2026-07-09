"""
engine/cronograma.py — Regra 2: montagem do cronograma draft (seção 3.5 do ROADMAP).
Lead times derivados das OFs reais (Mapa SEM 2637) — DRAFT para validação.
Simplificação documentada: dias corridos, sem feriados/fins de semana.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from engine.models import Cronograma, FaseCronograma, MatchPedido
from parsers.comum import semana_aass


def montar_cronograma(
    descricao_artigo: str,
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

    # 1. Detectar rota pelo nome do artigo
    rota_nome = _detectar_rota(descricao_artigo, rotas_cfg)
    rota = rotas_cfg.get(rota_nome, rotas_cfg["DEFAULT"])

    # 2. Calcular duração da fase PCP (dinâmica — seção 3.5)
    pcp_dias = _calcular_pcp_dias(match, fases_dias, lt_futuro, cfg)

    # 3. Sobrescrever durações por rota (overrides)
    overrides = overrides_cfg.get(rota_nome, {})

    # 4. Calcular cronograma
    fases: list[FaseCronograma] = []
    cursor = hoje

    for nome_fase in rota:
        if nome_fase == "PCP":
            dias = pcp_dias
        else:
            # Verificar override de rota, depois default
            dias = overrides.get(nome_fase, fases_dias.get(nome_fase, 1))

        inicio = cursor
        fim = cursor + timedelta(days=dias)
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
    Verifica keywords na ordem de especificidade.
    """
    desc_upper = descricao.upper()

    # Ordem de detecção (mais específico primeiro)
    for chave in ["PIJAMA", "REGATA", "VESTIDO"]:
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

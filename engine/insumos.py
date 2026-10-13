"""
engine/insumos.py — Regra 1: avaliação de status de insumos (seção 3.4 do ROADMAP).
OK_ESTOQUE | OK_FUTURO | FALTA + bloqueante/não-bloqueante.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from engine.models import MatchInsumo, Cronograma
from parsers.comum import avancar_dias_uteis_excia
from api.setor_adapter import normalizar_nome_setor


# Status possíveis
STATUS_OK_ESTOQUE = "OK_ESTOQUE"
STATUS_OK_FUTURO = "OK_FUTURO"
STATUS_FALTA = "FALTA"


def avaliar_insumos(
    insumos: list[MatchInsumo],
    cronograma: Optional[Cronograma],
    hoje: date,
    cfg: dict,
) -> list[MatchInsumo]:
    """
    Avalia o status de cada insumo conforme seção 3.4.
    Preenche: status, disponivel_em, fase_consumo, bloqueante, previsao_tipo, previsao_detalhe.
    Retorna lista de insumos atualizada (in-place + retorno).
    """
    lt = cfg["lead_times_estoque_futuro_dias"]
    insumo_fase_cfg = cfg.get("insumo_fase_consumo", {})
    fase_default = cfg.get("fase_consumo_default", "CORTE")

    for ins in insumos:
        _avaliar_insumo(ins, hoje, lt, insumo_fase_cfg, fase_default, cronograma)

    return insumos


def _avaliar_insumo(
    ins: MatchInsumo,
    hoje: date,
    lt: dict,
    insumo_fase_cfg: dict,
    fase_default: str,
    cronograma: Optional[Cronograma],
) -> None:
    """Avalia um único insumo."""
    necessario = ins.necessario

    # ── Determinar fase de consumo ─────────────────────────────────────────
    # Se já veio preenchida pelo MrpAdapter (setor real da API), manter.
    # Caso contrário, inferir pela keyword da descrição (fallback para PDF/legado).
    if not ins.fase_consumo:
        ins.fase_consumo = _determinar_fase(ins.descricao, insumo_fase_cfg, fase_default)

    # ── Status: OK_ESTOQUE ─────────────────────────────────────────────────
    gap = necessario - ins.aloc_estoque
    if gap <= 0:
        ins.status = STATUS_OK_ESTOQUE
        ins.previsao_tipo = "ESTOQUE"
        ins.previsao_detalhe = ""
        ins.disponivel_em = None
        ins.bloqueante = False
        return

    # ── Status: OK_FUTURO (coberto por estoque futuro) ─────────────────────
    # Verificar cada coluna futura em ordem de preferência (menor prazo primeiro)
    colunas_futuras = [
        ("Compra", ins.aloc_compra, lt.get("compra", 7)),
        ("Tecelagem", ins.aloc_tecelagem, lt.get("tecelagem", 7)),
        ("Pend.Tint", ins.aloc_pend_tint, lt.get("pend_tinturaria", 14)),
        ("Tinturaria", ins.aloc_tinturaria, lt.get("tinturaria", 14)),
    ]

    saldo_cobrir = gap
    disponivel_mais_tarde = hoje
    algum_futuro_cobre = False

    for nome_col, aloc, lead_time in colunas_futuras:
        if aloc > 0:
            saldo_cobrir -= aloc
            data_disp = avancar_dias_uteis_excia(hoje, lead_time)
            if data_disp > disponivel_mais_tarde:
                disponivel_mais_tarde = data_disp
            algum_futuro_cobre = True
            if saldo_cobrir <= 0.01:
                break

    if algum_futuro_cobre and saldo_cobrir <= 0.01:
        ins.status = STATUS_OK_FUTURO
        ins.previsao_tipo = "A_CAMINHO"
        ins.previsao_detalhe = ""
        ins.disponivel_em = disponivel_mais_tarde
        ins.bloqueante = _e_bloqueante(ins, cronograma)
        return

    # ── Status: FALTA ──────────────────────────────────────────────────────
    ins.status = STATUS_FALTA

    # Verificar se é tecido/malha/ribana
    desc_up = (ins.descricao or "").upper()
    eh_malha_ribana = (
        ins.cascata_info is not None
        or "MALHA" in desc_up
        or "RIBANA" in desc_up
        or (ins.cod_insumo and ins.cod_insumo.startswith("03"))
    )

    if eh_malha_ribana:
        cascata = ins.cascata_info or {}
        tem_crua = cascata.get("tem_crua", False)
        atende_crua = cascata.get("atende_via_tinturaria", False)
        if tem_crua and atende_crua:
            lt_tint = lt.get("tinturaria", 14)
            ins.previsao_tipo = "ESTIMATIVA"
            ins.disponivel_em = avancar_dias_uteis_excia(hoje, lt_tint)
            ins.previsao_detalhe = "via tinturaria da malha crua em estoque"
        else:
            lt_tec = lt.get("tecelagem", 7)
            lt_tint = lt.get("tinturaria", 14)
            ins.previsao_tipo = "SEM_PREVISAO"
            ins.disponivel_em = None
            ins.previsao_detalhe = f"necessita tecelagem ({lt_tec} d) + tinturaria ({lt_tint} d) = {lt_tec + lt_tint} dias úteis"
    else:
        lt_compra = lt.get("compra", 7)
        ins.previsao_tipo = "ESTIMATIVA"
        ins.disponivel_em = avancar_dias_uteis_excia(hoje, lt_compra)
        ins.previsao_detalhe = "estimativa de compra"

    ins.bloqueante = _e_bloqueante(ins, cronograma)
    ins.avisos.append(
        f"Insumo FALTA: acionar COMPRAS para {ins.descricao} ({ins.cod_insumo})"
    )


def _determinar_fase(descricao: str, insumo_fase_cfg: dict, fase_default: str) -> str:
    """
    Determina a fase de consumo do insumo por keyword na descrição.
    Conforme config insumo_fase_consumo (seção 4 do ROADMAP).
    Match: keyword está CONTIDA na descrição (case-insensitive).
    Múltiplas keywords: usa a mais específica (mais longa que bate).
    """
    desc_upper = descricao.upper()

    # Ordenar por tamanho da keyword (maior = mais específica) para priorizar match exato
    candidatos = sorted(insumo_fase_cfg.items(), key=lambda kv: len(kv[0]), reverse=True)

    for keyword, fase in candidatos:
        if keyword.upper() in desc_upper:
            return fase

    return fase_default


def _e_bloqueante(ins: MatchInsumo, cronograma: Optional[Cronograma]) -> bool:
    """
    Determina se o insumo é bloqueante: disponivel_em > data_inicio(fase_consumo).
    Normaliza nomes de fase com normalizar_nome_setor antes de comparar.
    """
    if cronograma is None or ins.disponivel_em is None:
        # Sem cronograma ou sem data (ex: SEM_PREVISAO em FALTA) → conservador
        return ins.status != STATUS_OK_ESTOQUE

    fase_ins_norm = normalizar_nome_setor(ins.fase_consumo)

    # Encontrar data de início da fase de consumo no cronograma
    for fase in cronograma.fases:
        if normalizar_nome_setor(fase.nome) == fase_ins_norm:
            return ins.disponivel_em > fase.inicio

    # Se houver cronogramas de partes, buscar em todas as partes
    if getattr(cronograma, "cronogramas_partes", None):
        for p_fases in cronograma.cronogramas_partes.values():
            for fase in p_fases:
                if normalizar_nome_setor(fase.nome) == fase_ins_norm:
                    return ins.disponivel_em > fase.inicio

    # Fase não encontrada no cronograma → conservador
    return ins.status != STATUS_OK_ESTOQUE

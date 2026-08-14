"""
engine/insumos.py — Regra 1: avaliação de status de insumos (seção 3.4 do ROADMAP).
OK_ESTOQUE | OK_FUTURO | FALTA + bloqueante/não-bloqueante.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from engine.models import MatchInsumo, Cronograma


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
    Preenche: status, disponivel_em, fase_consumo, bloqueante.
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
        ins.disponivel_em = hoje
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
            data_disp = hoje + timedelta(days=lead_time)
            if data_disp > disponivel_mais_tarde:
                disponivel_mais_tarde = data_disp
            algum_futuro_cobre = True
            if saldo_cobrir <= 0.01:
                break

    if algum_futuro_cobre and saldo_cobrir <= 0.01:
        ins.status = STATUS_OK_FUTURO
        ins.disponivel_em = disponivel_mais_tarde
        ins.bloqueante = _e_bloqueante(ins, cronograma)
        return

    # ── Status: FALTA ──────────────────────────────────────────────────────
    ins.status = STATUS_FALTA
    # Estimativa: precisa comprar → lead time de compra
    ins.disponivel_em = hoje + timedelta(days=lt.get("compra", 7))
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
    bloqueante = disponivel_em > data_inicio(fase_de_consumo no cronograma draft).
    """
    if cronograma is None or ins.disponivel_em is None:
        # Sem cronograma, assumir bloqueante por conservadorismo
        return ins.status != STATUS_OK_ESTOQUE

    # Encontrar data de início da fase de consumo no cronograma
    for fase in cronograma.fases:
        if fase.nome == ins.fase_consumo:
            return ins.disponivel_em > fase.inicio

    # Fase não encontrada no cronograma → conservador
    return ins.status != STATUS_OK_ESTOQUE

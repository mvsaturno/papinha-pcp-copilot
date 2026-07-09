"""
engine/capacidade.py — Regra 3: checagem de capacidade semanal (seção 3.6 do ROADMAP).
Alertas globais de atraso e semanas estouradas.
Verificação por pedido: cabe na semana alvo?
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from engine.models import AnaliseCapacidade, CapacidadeSemanal
from parsers.comum import aass_add, semana_aass, sexta_da_semana, formatar_data_br


def alertas_globais_capacidade(
    cap: CapacidadeSemanal,
    hoje: date,
    cfg: dict,
) -> list[str]:
    """
    Gera alertas globais de capacidade (independentes de pedido):
    1. Semanas com pend > limite (estouradas)
    2. Peças em semanas anteriores à semana atual (atraso)
    Conforme seção 3.6.
    """
    alertas = []
    semana_atual = semana_aass(hoje)
    limite = cfg["capacidade"]["limite_total_semana"]

    # Atraso: semanas anteriores com pend > 0
    atraso_semanas = {s: p for s, p in cap.periodos.items() if s < semana_atual and p > 0}
    if atraso_semanas:
        total_atraso = sum(atraso_semanas.values())
        sem_min = min(atraso_semanas)
        sem_max = max(atraso_semanas)
        alertas.append(
            f"⚠️ {total_atraso:,} peças em atraso (semanas {sem_min}–{sem_max})"
            .replace(",", ".")
        )

    # Semanas estouradas
    for s, pend in cap.periodos.items():
        if pend > limite:
            excesso = pend - limite
            alertas.append(
                f"🔴 Semana {s} estourada: {pend:,} peças ({excesso:,} acima do limite {limite:,})"
                .replace(",", ".")
            )

    return alertas


def verificar_capacidade_pedido(
    qtd_of: int,
    semana_alvo: int,
    semana_minima: int,
    cap: CapacidadeSemanal,
    cfg: dict,
) -> AnaliseCapacidade:
    """
    Verifica se o pedido cabe na semana alvo e sugere alternativas.
    Conforme seção 3.8 do ROADMAP.
    """
    limite = cfg["capacidade"]["limite_total_semana"]
    semanas_ausentes_zero = cfg["capacidade"].get("semanas_ausentes_sao_zero", True)

    def pend(s: int) -> int:
        if semanas_ausentes_zero:
            return cap.periodos.get(s, 0)
        return cap.periodos.get(s, 0)

    # Encontrar semana sugerida (seção 3.8, lógica de candidatos)
    semana_sugerida = None

    # a) Menor W no intervalo [semana_minima .. semana_alvo] com capacidade OK
    s = semana_minima
    while s <= semana_alvo:
        if (pend(s) + qtd_of) <= limite:
            semana_sugerida = s
            break
        s = aass_add(s, 1)

    # b) Se nenhuma: menor W > alvo com capacidade OK e W >= semana_minima
    if semana_sugerida is None:
        s = max(aass_add(semana_alvo, 1), semana_minima)
        limite_busca = aass_add(semana_alvo, 12)  # até 12 semanas à frente
        while s <= limite_busca:
            if (pend(s) + qtd_of) <= limite:
                semana_sugerida = s
                break
            s = aass_add(s, 1)

    # Calcular intervalo dinâmico de semanas para exibição na UI
    # Garante que a semana física mínima e a semana sugerida estejam na listagem
    ref_sug = semana_sugerida if semana_sugerida is not None else semana_alvo
    start_sem = min(semana_minima, ref_sug, aass_add(semana_alvo, -2))
    end_sem = max(ref_sug, aass_add(semana_alvo, 3))

    semanas_exibir = []
    curr = start_sem
    while curr <= end_sem:
        p = pend(curr)
        situacao = "✅ OK" if (p + qtd_of) <= limite else "❌ Estourado"
        semanas_exibir.append({
            "aass": curr,
            "pend_atual": p,
            "mais_este": p + qtd_of,
            "limite": limite,
            "situacao": situacao,
        })
        curr = aass_add(curr, 1)

    # Verificar se cabe no alvo
    cabe_no_alvo = (pend(semana_alvo) + qtd_of) <= limite

    avisos = []
    if not cabe_no_alvo:
        avisos.append(
            f"Capacidade da semana {semana_alvo} estourada: "
            f"{pend(semana_alvo)} + {qtd_of} = {pend(semana_alvo) + qtd_of} > {limite}"
        )

    return AnaliseCapacidade(
        semana_alvo=semana_alvo,
        qtd_of=qtd_of,
        semanas_relevantes=semanas_exibir,
        cabe_no_alvo=cabe_no_alvo,
        semana_sugerida=semana_sugerida,
        avisos=avisos,
    )

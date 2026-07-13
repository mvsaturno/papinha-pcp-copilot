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
    Verifica se o pedido cabe na semana alvo e sugere alternativas priorizando JIT.
    Conforme seção 3.8 do ROADMAP (Sprint 2).
    """
    limite = cfg["capacidade"]["limite_total_semana"]
    semanas_ausentes_zero = cfg["capacidade"].get("semanas_ausentes_sao_zero", True)
    
    autonomia = cfg["geral"].get("semanas_autonomia_pcp", 3)
    permitir_margem = cfg["geral"].get("permitir_consumir_margem", True)
    semanas_antes = cfg["geral"].get("semanas_antes_entrega_cliente", 2)
    ociosidade_alerta_pct = cfg["capacidade"].get("ociosidade_alerta_pct", 40)
    semana_cliente = aass_add(semana_alvo, semanas_antes)

    def pend(s: int) -> int:
        if semanas_ausentes_zero:
            return cap.periodos.get(s, 0)
        return cap.periodos.get(s, 0)

    # Encontrar semana sugerida priorizando Backward (JIT)
    semana_sugerida = None
    
    # helper para criar listas de semanas
    def range_semanas(start, end, step=-1):
        # se start/end estiverem fora de ordem para o step, retorna lista vazia
        lst = []
        curr = start
        if step == -1:
            while curr >= end:
                lst.append(curr)
                curr = aass_add(curr, -1)
        else:
            while curr <= end:
                lst.append(curr)
                curr = aass_add(curr, 1)
        return lst

    # Construir janelas
    # 1. Janela de autonomia [alvo, alvo-1, ..., alvo-autonomia]
    janela = range_semanas(semana_alvo, aass_add(semana_alvo, -autonomia), step=-1)
    
    # 2. Extra 2: consome margem [alvo+1 .. semana_cliente-1]
    extra_2 = range_semanas(aass_add(semana_alvo, 1), aass_add(semana_cliente, -1), step=1) if permitir_margem else []
    
    # 3. Extra 1: antecipação além da autonomia [alvo-autonomia-1 .. semana_minima]
    extra_1 = range_semanas(aass_add(semana_alvo, -autonomia-1), semana_minima, step=-1)
    
    # Ordem de busca
    candidatas = janela + extra_2 + extra_1
    
    for s in candidatas:
        if s >= semana_minima and (pend(s) + qtd_of) <= limite:
            semana_sugerida = s
            break
            
    # Se não coube em nenhuma (ou não achou), procura a primeira livre após alvo
    if semana_sugerida is None:
        # Procurar >= semana_cliente
        s = max(semana_cliente, semana_minima)
        limite_busca = aass_add(semana_alvo, 12)
        while s <= limite_busca:
            if (pend(s) + qtd_of) <= limite:
                semana_sugerida = s
                break
            s = aass_add(s, 1)

    # Calcular intervalo dinâmico de semanas para exibição na UI
    # Exibe a janela de autonomia toda e até alvo+1 se permitida a margem
    start_sem = min(semana_minima, aass_add(semana_alvo, -autonomia), semana_sugerida or semana_alvo)
    end_sem = max(aass_add(semana_alvo, 1 if permitir_margem else 0), semana_sugerida or semana_alvo)

    semanas_exibir = []
    curr = start_sem
    while curr <= end_sem:
        p = pend(curr)
        situacao = "✅ OK" if (p + qtd_of) <= limite else "❌ Estourado"
        # Calcular ociosidade na janela (pct livre)
        pct_livre = ((limite - p) / limite) * 100 if limite > 0 else 0
        is_ociosa = pct_livre > ociosidade_alerta_pct and (aass_add(semana_alvo, -autonomia) <= curr <= semana_alvo)

        semanas_exibir.append({
            "aass": curr,
            "pend_atual": p,
            "mais_este": p + qtd_of,
            "limite": limite,
            "situacao": situacao,
            "ociosa": is_ociosa,
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

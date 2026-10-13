"""
engine/capacidade.py — Regra 3: checagem de capacidade semanal (seção 3.6 do ROADMAP).
Alertas globais de atraso e semanas estouradas.
Verificação por pedido: cabe na semana alvo?
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from engine.models import AnaliseCapacidade, CapacidadeSemanal
from parsers.comum import aass_add, semana_aass, sexta_da_semana, formatar_data_br, semanas_entre


def aass_min(a: int, b: int) -> int:
    return a if semanas_entre(b, a) >= 0 else b


def aass_max(a: int, b: int) -> int:
    return a if semanas_entre(a, b) >= 0 else b


def alertas_globais_capacidade(
    cap: CapacidadeSemanal,
    hoje: date,
    cfg: dict,
) -> list[str]:
    """
    Gera alertas globais de capacidade (independentes de pedido):
    1. Semanas com pend > limite (estouradas) na programação ativa (>= semana_atual)
    Conforme seção 3.6 do ROADMAP.
    """
    alertas = []
    semana_atual = semana_aass(hoje)
    limite = cfg["capacidade"]["limite_total_semana"]

    # Semanas estouradas na programação ativa (>= semana_atual)
    for s, pend in cap.periodos.items():
        if semanas_entre(s, semana_atual) >= 0 and pend > limite:
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
    
    # helper para criar listas de semanas sem quebrar na virada de ano
    def range_semanas(start, end, step=-1):
        lst = []
        curr = start
        if step == -1:
            while semanas_entre(curr, end) >= 0:
                lst.append(curr)
                curr = aass_add(curr, -1)
        else:
            while semanas_entre(end, curr) >= 0:
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
        if semanas_entre(s, semana_minima) >= 0 and (pend(s) + qtd_of) <= limite:
            semana_sugerida = s
            break
            
    # Se não coube em nenhuma (ou não achou), procura a primeira livre após alvo
    if semana_sugerida is None:
        # Procurar >= semana_cliente
        s = aass_max(semana_cliente, semana_minima)
        limite_busca = aass_add(semana_alvo, 12)
        while semanas_entre(limite_busca, s) >= 0:
            if (pend(s) + qtd_of) <= limite:
                semana_sugerida = s
                break
            s = aass_add(s, 1)

    # Calcular intervalo dinâmico de semanas para exibição na UI
    candidatos_start = [semana_minima, aass_add(semana_alvo, -autonomia)]
    if semana_sugerida:
        candidatos_start.append(semana_sugerida)
    else:
        candidatos_start.append(semana_alvo)

    start_sem = candidatos_start[0]
    for cs in candidatos_start[1:]:
        start_sem = aass_min(start_sem, cs)

    candidatos_end = [aass_add(semana_alvo, 1 if permitir_margem else 0)]
    if semana_sugerida:
        candidatos_end.append(semana_sugerida)
    else:
        candidatos_end.append(semana_alvo)

    end_sem = candidatos_end[0]
    for ce in candidatos_end[1:]:
        end_sem = aass_max(end_sem, ce)

    semanas_exibir = []
    curr = start_sem
    jan_ini = aass_add(semana_alvo, -autonomia)

    while semanas_entre(end_sem, curr) >= 0:
        p = pend(curr)
        situacao = "✅ OK" if (p + qtd_of) <= limite else "❌ Estourado"
        # Calcular ociosidade na janela (pct livre)
        pct_livre = ((limite - p) / limite) * 100 if limite > 0 else 0
        is_ociosa = pct_livre > ociosidade_alerta_pct and (semanas_entre(curr, jan_ini) >= 0 and semanas_entre(semana_alvo, curr) >= 0)

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

    janela_inicio = aass_add(semana_alvo, -autonomia)
    janela_fim = semana_alvo

    return AnaliseCapacidade(
        semana_alvo=semana_alvo,
        qtd_of=qtd_of,
        semanas_relevantes=semanas_exibir,
        cabe_no_alvo=cabe_no_alvo,
        semana_sugerida=semana_sugerida,
        avisos=avisos,
        janela_autonomia={"inicio": janela_inicio, "fim": janela_fim},
    )

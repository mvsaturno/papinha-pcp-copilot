"""
parsers/comum.py — Utilitários de parsing: números BR, datas BR, semanas ISO, aritmética.
Nenhum número mágico aqui — todos os parâmetros vêm de config ou são constantes ISO.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional


# ──────────────────────────────────────────────
# Números no formato brasileiro
# ──────────────────────────────────────────────

def parse_num_br(s: str) -> float:
    """
    Converte string numérica no formato brasileiro para float.
    Ponto = separador de milhar, vírgula = decimal.
    Ex: '11.460,000' → 11460.0, '91,136' → 91.136
    Aceita strings coladas ou com espaços.
    """
    s = str(s).strip()
    # Remove pontos de milhar, substitui vírgula decimal
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Não foi possível converter '{s}' como número brasileiro")


def formatar_num_br(v: float, decimais: int = 0) -> str:
    """Formata um float no padrão brasileiro."""
    if decimais == 0:
        return f"{int(round(v)):,}".replace(",", ".")
    return f"{v:,.{decimais}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ──────────────────────────────────────────────
# Arredondamento
# ──────────────────────────────────────────────

def arredondar(valor: float, modo: str = "half_up") -> int:
    """
    Arredondamento configurável.
    modo: 'half_up' (padrão) | 'ceil' / 'UP' (sempre para cima) | 'floor' / 'DOWN' (sempre para baixo)
    """
    modo_norm = modo.upper()
    if modo_norm in ("CEIL", "UP"):
        return math.ceil(valor)
    if modo_norm in ("FLOOR", "DOWN"):
        return math.floor(valor)
    # half_up: 0.5 arredonda para cima (padrão)
    return math.floor(valor + 0.5)


# ──────────────────────────────────────────────
# Datas no formato brasileiro
# ──────────────────────────────────────────────

def parse_data_br(s: str) -> date:
    """
    Converte data no formato DD/MM/YY ou DD/MM/YYYY para date.
    Século: 20xx para anos de 2 dígitos.
    """
    s = s.strip()
    partes = s.split("/")
    if len(partes) != 3:
        raise ValueError(f"Data inválida: '{s}' — esperado DD/MM/YY ou DD/MM/YYYY")
    d, m, a = partes
    if len(a) == 2:
        a = "20" + a
    return date(int(a), int(m), int(d))


def formatar_data_br(d: date) -> str:
    """Formata date como DD/MM/AAAA."""
    return d.strftime("%d/%m/%Y")


# ──────────────────────────────────────────────
# Semanas ISO (formato AASS — ex: 2637 = ano 26, semana 37)
# ──────────────────────────────────────────────

def semana_aass(d: date) -> int:
    """
    Retorna a semana ISO no formato AASS (2 dígitos do ano + 2 dígitos da semana).
    Ex: date(2026, 9, 4) → 2636 (semana 36 do ano 2026).
    Validado: 04/09/2026 = semana 36 (confirmado pelo gestor).
    """
    iso = d.isocalendar()
    ano2 = iso.year % 100
    return int(f"{ano2:02d}{iso.week:02d}")


def aass_para_date(aass: int) -> tuple[int, int]:
    """Decompõe AASS em (ano_completo, semana_iso)."""
    aass_str = f"{aass:04d}"
    ano2 = int(aass_str[:2])
    semana = int(aass_str[2:])
    ano4 = 2000 + ano2
    return ano4, semana


def sexta_da_semana(aass: int) -> date:
    """
    Retorna a sexta-feira da semana ISO AASS.
    O Excia usa sexta como fim da semana produtiva.
    Validado: semana 36/2026 termina sexta 04/09/2026.
    """
    ano4, semana = aass_para_date(aass)
    jan4 = date(ano4, 1, 4)  # 4 de janeiro sempre está na semana 1 ISO
    iso_jan4 = jan4.isocalendar()
    segunda_sem1 = jan4 - timedelta(days=iso_jan4.weekday - 1)
    segunda_alvo = segunda_sem1 + timedelta(weeks=semana - 1)
    sexta = segunda_alvo + timedelta(days=4)  # sexta = segunda + 4
    return sexta


def quarta_da_semana(aass: int) -> date:
    """
    Retorna a quarta-feira da semana ISO AASS.
    O Excia ancora o fim da embalagem na quarta-feira da semana da OF.
    Validado: semana 42/2026 termina a embalagem em 14/10/2026.
    """
    ano4, semana = aass_para_date(aass)
    jan4 = date(ano4, 1, 4)
    iso_jan4 = jan4.isocalendar()
    segunda_sem1 = jan4 - timedelta(days=iso_jan4.weekday - 1)
    segunda_alvo = segunda_sem1 + timedelta(weeks=semana - 1)
    quarta = segunda_alvo + timedelta(days=2)  # quarta = segunda + 2
    return quarta


# ──────────────────────────────────────────────
# Feriados Nacionais Brasileiros
# ──────────────────────────────────────────────

FERIADOS_NACIONAIS = {
    # 2025
    date(2025, 1, 1),   date(2025, 3, 3),   date(2025, 3, 4),
    date(2025, 4, 18),  date(2025, 4, 21),  date(2025, 5, 1),
    date(2025, 6, 19),  date(2025, 9, 7),   date(2025, 10, 12),
    date(2025, 11, 2),  date(2025, 11, 15), date(2025, 11, 20),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1),   date(2026, 2, 16),  date(2026, 2, 17),
    date(2026, 4, 3),   date(2026, 4, 21),  date(2026, 5, 1),
    date(2026, 6, 4),   date(2026, 9, 7),   date(2026, 10, 12),
    date(2026, 11, 2),  date(2026, 11, 15), date(2026, 11, 20),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1),   date(2027, 2, 8),   date(2027, 2, 9),
    date(2027, 3, 26),  date(2027, 4, 21),  date(2027, 5, 1),
    date(2027, 5, 27),  date(2027, 9, 7),   date(2027, 10, 12),
    date(2027, 11, 2),  date(2027, 11, 15), date(2027, 11, 20),
    date(2027, 12, 25),
}

def eh_dia_util(d: date) -> bool:
    """Verifica se uma data é dia útil (segunda a sexta e fora de feriados nacionais)."""
    return d.weekday() < 5 and d not in FERIADOS_NACIONAIS

def recuar_dias_uteis_excia(data_saida: date, duracao_dias: int, eh_ultima: bool = False) -> date:
    """
    Calcula a data de entrada no padrão do Excia a partir da data de saída.
    No Excia, a data de saída de uma etapa é a data de entrada da etapa seguinte.
    Para a última etapa (Embalagem), o próprio dia da saída é o último dia trabalhado.
    Para as etapas anteriores, os dias trabalhados são os dias anteriores até a entrada.
    """
    if duracao_dias <= 0:
        return data_saida
    cur = data_saida
    dias_contados = 0
    if eh_ultima:
        if eh_dia_util(cur):
            dias_contados = 1
            if duracao_dias == 1:
                return cur
    while True:
        cur -= timedelta(days=1)
        if eh_dia_util(cur):
            dias_contados += 1
            if dias_contados >= duracao_dias:
                return cur

def avancar_dias_uteis_excia(data_entrada: date, duracao_dias: int) -> date:
    """Avança N dias úteis a partir da data de entrada considerando feriados."""
    if duracao_dias <= 0:
        return data_entrada
    cur = data_entrada
    dias_contados = 0
    while dias_contados < duracao_dias:
        cur += timedelta(days=1)
        if eh_dia_util(cur):
            dias_contados += 1
    return cur


def contar_dias_uteis_excia(data_inicio: date, data_fim: date) -> int:
    """Conta a quantidade de dias úteis entre data_inicio e data_fim."""
    if data_inicio >= data_fim:
        return 0
    cur = data_inicio
    dias = 0
    while cur < data_fim:
        cur += timedelta(days=1)
        if eh_dia_util(cur):
            dias += 1
    return dias


def aass_add(aass: int, n_semanas: int) -> int:
    """
    Soma n_semanas ao período AASS, cruzando ano corretamente.
    Suporta n_semanas negativo.
    """
    sexta = sexta_da_semana(aass)
    nova_data = sexta + timedelta(weeks=n_semanas)
    return semana_aass(nova_data)


def dias_entre_semanas(aass_inicio: int, aass_fim: int) -> int:
    """Diferença em dias entre o início (segunda) de duas semanas."""
    ano_i, sem_i = aass_para_date(aass_inicio)
    ano_f, sem_f = aass_para_date(aass_fim)
    # usa a sexta de cada semana como referência
    d_i = sexta_da_semana(aass_inicio)
    d_f = sexta_da_semana(aass_fim)
    return (d_f - d_i).days


# ──────────────────────────────────────────────
# Testes rápidos de sanidade (rodáveis diretamente)
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Golden tests da seção 8 do ROADMAP
    assert semana_aass(date(2026, 9, 4)) == 2636, f"Esperado 2636, got {semana_aass(date(2026, 9, 4))}"
    assert semana_aass(date(2026, 7, 7)) == 2628, f"Esperado 2628, got {semana_aass(date(2026, 7, 7))}"
    assert parse_num_br("11.460,000") == 11460.0
    assert parse_num_br("91,136") == 91.136
    assert arredondar(2701 * 1.07) == 2890
    assert arredondar(3000 * 1.07) == 3210
    assert arredondar(1198 * 1.07) == 1282
    assert arredondar(1000 * 1.07) == 1070
    assert sexta_da_semana(2636) == date(2026, 9, 4)
    print("✅ Todos os testes de comum.py passaram!")

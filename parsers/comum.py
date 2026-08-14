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

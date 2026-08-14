"""
parsers/capacidade_parser.py — Parser do PDF "Resumo por Período" (Capacidade Semanal).
Estratégia: simples — busca linhas no padrão AASS + quantidade.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Optional

import pdfplumber

from engine.models import CapacidadeSemanal
from parsers.comum import parse_num_br, parse_data_br


# Padrão de linha de capacidade: 4 dígitos (AASS) seguido de número (peças)
_RE_PERIODO = re.compile(r"\b(\d{4})\s+([\d.]+(?:,\d+)?)\b")

# Faixa de períodos AASS plausível (2600–2799 = anos 2026–2027)
_AASS_MIN = 2600
_AASS_MAX = 2799


def parse_capacidade(pdf_bytes: bytes) -> CapacidadeSemanal:
    """
    Extrai o mapa {aass: qtd_pendente} do PDF de Resumo por Período / Relatório de Capacidade.
    Prioriza a seção 'Resumo por Periodo' (padrão oficial Excia nas páginas de fechamento).
    Saída: CapacidadeSemanal com dict ordenado + data_relatorio se localizável.
    """
    periodos: dict[int, int] = {}
    data_relatorio: Optional[date] = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # 1. Estratégia Principal: Procurar a seção 'Resumo por Periodo'
        encontrou_secao = False
        for page in pdf.pages:
            texto = page.extract_text() or ""
            # Capturar data do relatório
            if data_relatorio is None:
                m_data = re.search(r"\b(\d{2}/\d{2}/\d{2,4})\b", texto)
                if m_data:
                    try:
                        data_relatorio = parse_data_br(m_data.group(1))
                    except Exception:
                        pass

            linhas = texto.splitlines()
            for l in linhas:
                l_clean = l.strip()
                if "Resumo por Periodo" in l_clean or "Resumo por Período" in l_clean:
                    encontrou_secao = True
                    continue

                if encontrou_secao:
                    # Linha esperada na tabela de resumo: '2633 28.026,00' ou '2649 3.102,00'
                    m = re.match(r"^(\d{4})\s+([\d.]+,\d{2})$", l_clean)
                    if m:
                        sem = int(m.group(1))
                        if _AASS_MIN <= sem <= _AASS_MAX:
                            qtd = int(float(m.group(2).replace(".", "").replace(",", ".")))
                            periodos[sem] = qtd

        # 2. Fallback caso o PDF não tenha a seção 'Resumo por Periodo'
        if not periodos:
            for page in pdf.pages:
                texto = page.extract_text() or ""
                for linha in texto.splitlines():
                    linha = linha.strip()
                    m = _RE_PERIODO.search(linha)
                    if not m:
                        continue
                    aass_str = m.group(1)
                    qtd_str = m.group(2)
                    aass = int(aass_str)

                    if not (_AASS_MIN <= aass <= _AASS_MAX):
                        continue

                    try:
                        qtd = int(parse_num_br(qtd_str))
                    except ValueError:
                        continue

                    if aass not in periodos:
                        periodos[aass] = qtd

    return CapacidadeSemanal(
        periodos=dict(sorted(periodos.items())),
        data_relatorio=data_relatorio,
    )

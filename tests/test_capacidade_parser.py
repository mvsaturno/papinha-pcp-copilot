"""
tests/test_capacidade_parser.py — Golden tests da seção 8 do ROADMAP para capacidade_parser.py
Valores extraídos manualmente do PDF "TESTE SEM.2637 CAPACIDADE PROD.pdf".
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.capacidade_parser import parse_capacidade

FIXTURE = Path(__file__).parent / "fixtures" / "capacidade.pdf"


@pytest.fixture(scope="module")
def cap():
    return parse_capacidade(FIXTURE.read_bytes())


class TestCapacidadeParser:

    def test_numero_de_periodos(self, cap):
        """Deve extrair 29 períodos conforme golden test."""
        assert len(cap.periodos) == 29, f"Esperado 29, got {len(cap.periodos)}"

    def test_sem_2634(self, cap):
        """cap[2634] == 91034 (golden value do ROADMAP)."""
        assert cap.periodos.get(2634) == 91034, f"Got {cap.periodos.get(2634)}"

    def test_sem_2637(self, cap):
        """cap[2637] == 11433 (golden value do ROADMAP)."""
        assert cap.periodos.get(2637) == 11433, f"Got {cap.periodos.get(2637)}"

    def test_sem_2652(self, cap):
        """cap[2652] == 3102 (golden value do ROADMAP)."""
        assert cap.periodos.get(2652) == 3102, f"Got {cap.periodos.get(2652)}"

    def test_periodos_ordenados(self, cap):
        """Períodos devem estar ordenados."""
        chaves = list(cap.periodos.keys())
        assert chaves == sorted(chaves)

    def test_todos_periodos_no_range(self, cap):
        """Todos os períodos devem estar no range AASS plausível (2600-2799)."""
        for aass in cap.periodos:
            assert 2600 <= aass <= 2799, f"Período fora do range: {aass}"

    def test_valores_positivos(self, cap):
        """Todas as quantidades devem ser não-negativas."""
        for aass, qtd in cap.periodos.items():
            assert qtd >= 0, f"Semana {aass}: qtd negativa {qtd}"

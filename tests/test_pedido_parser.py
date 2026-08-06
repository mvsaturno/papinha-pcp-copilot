"""
tests/test_pedido_parser.py — Golden tests da seção 8 do ROADMAP para pedido_parser.py
Valores extraídos manualmente do PDF "TESTE SEM.2637 PEDIDOS.pdf".
"""

import pytest
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.pedido_parser import parse_pedido

FIXTURE = Path(__file__).parent / "fixtures" / "pedidos.pdf"


@pytest.fixture(scope="module")
def pedidos():
    return parse_pedido(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def pedidos_por_numero(pedidos):
    return {p.numero: p for p in pedidos}


class TestPedidoParser:

    def test_total_pedidos(self, pedidos):
        """Deve extrair exatamente 6 pedidos."""
        numeros = [p.numero for p in pedidos]
        assert len(pedidos) == 6, f"Esperado 6 pedidos, got {len(pedidos)}: {numeros}"

    def test_numeros_dos_pedidos(self, pedidos):
        """Os 6 pedidos extraídos devem ter exatamente estes números."""
        numeros = sorted([p.numero for p in pedidos])
        esperados = sorted(["102559", "102562", "102578", "102580", "102622", "94736"])
        assert numeros == esperados, f"Números incorretos: {numeros}"

    def test_pedido_102559_artigo(self, pedidos_por_numero):
        """102559: artigo 4104040."""
        p = pedidos_por_numero["102559"]
        assert len(p.linhas) == 1
        assert p.linhas[0].codigo == "4104040"

    def test_pedido_102559_cor(self, pedidos_por_numero):
        """102559: cor 00088 VERDE MUSGO."""
        l = pedidos_por_numero["102559"].linhas[0]
        assert l.cor == "00088"
        assert "VERDE MUSGO" in l.desc_cor.upper()

    def test_pedido_102559_grade(self, pedidos_por_numero):
        """102559: grade {PP:319, P:641, M:728, G:634, GG:379}."""
        grade = pedidos_por_numero["102559"].linhas[0].grade
        assert grade.get("PP") == 319
        assert grade.get("P") == 641
        assert grade.get("M") == 728
        assert grade.get("G") == 634
        assert grade.get("GG") == 379

    def test_pedido_102559_total(self, pedidos_por_numero):
        """102559: total 2701 peças."""
        l = pedidos_por_numero["102559"].linhas[0]
        assert l.qtde_total == 2701

    def test_pedido_102559_entrega(self, pedidos_por_numero):
        """102559: entrega 04/11/2026."""
        p = pedidos_por_numero["102559"]
        assert p.entrega == date(2026, 11, 4)

    def test_pedido_94736_grade_sem_pp(self, pedidos_por_numero):
        """94736 (pijama): grade SEM PP — prova grade dinâmica."""
        grade = pedidos_por_numero["94736"].linhas[0].grade
        assert "PP" not in grade, f"PP não deveria estar na grade do pijama: {grade}"
        assert grade.get("P") == 212
        assert grade.get("M") == 196
        assert grade.get("G") == 208
        assert grade.get("GG") == 184

    def test_pedido_94736_total(self, pedidos_por_numero):
        """94736: total 800 peças."""
        l = pedidos_por_numero["94736"].linhas[0]
        assert l.qtde_total == 800

    def test_pedido_94736_entrega(self, pedidos_por_numero):
        """94736: entrega 07/12/2026."""
        p = pedidos_por_numero["94736"]
        assert p.entrega == date(2026, 12, 7)

    def test_soma_grade_igual_total(self, pedidos):
        """Soma de cada grade deve ser igual ao qtde_total."""
        for p in pedidos:
            for l in p.linhas:
                soma = sum(l.grade.values())
                assert soma == l.qtde_total, (
                    f"Pedido {p.numero} artigo {l.codigo}: "
                    f"soma={soma} ≠ total={l.qtde_total}"
                )

    def test_sem_avisos_de_parsing(self, pedidos):
        """Nenhum pedido deve ter avisos de parsing."""
        for p in pedidos:
            assert not p.avisos_parsing, (
                f"Pedido {p.numero} tem avisos: {p.avisos_parsing}"
            )

    def test_pedido_102562(self, pedidos_por_numero):
        """102562: artigo 4104046, entrega 03/11/2026, total 3000."""
        p = pedidos_por_numero["102562"]
        l = p.linhas[0]
        assert l.codigo == "4104046"
        assert l.qtde_total == 3000
        assert p.entrega == date(2026, 11, 3)

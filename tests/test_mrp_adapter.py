"""
tests/test_mrp_adapter.py — Testes unitários para o MrpAdapter e filtragem por faixa/tamanho.
"""

import unittest
from engine.models import LinhaPedido
from api.mrp_adapter import _calcular_qtde_aplicavel, _resolver_cor_insumo


class TestMrpAdapter(unittest.TestCase):
    def test_calcular_qtde_aplicavel_generico(self):
        linha = LinhaPedido(
            ordem="1",
            codigo="4104049",
            descricao="REGATA TESTE",
            cor="00278",
            desc_cor="VERDE",
            grade={"PP": 2500.0},
            qtde_total=2500.0
        )
        # Faixa 00 / vazia / geral
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "00"}, linha), 2500.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": ""}, linha), 2500.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "TODOS"}, linha), 2500.0)

    def test_calcular_qtde_aplicavel_tamanho_especifico(self):
        linha = LinhaPedido(
            ordem="1",
            codigo="4104049",
            descricao="REGATA TESTE",
            cor="00278",
            desc_cor="VERDE",
            grade={"PP": 2500.0},
            qtde_total=2500.0
        )
        # PP deve ter 2500
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "PP"}, linha), 2500.0)
        # Outros tamanhos não existentes devem ser 0
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "P"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "M"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "G"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "GG"}, linha), 0.0)

    def test_calcular_qtde_aplicavel_grade_multipla(self):
        linha = LinhaPedido(
            ordem="1",
            codigo="4104049",
            descricao="REGATA TESTE",
            cor="00278",
            desc_cor="VERDE",
            grade={"P": 500.0, "M": 1000.0, "G": 800.0},
            qtde_total=2300.0
        )
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "P"}, linha), 500.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "M"}, linha), 1000.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "G"}, linha), 800.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "GG"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "00"}, linha), 2300.0)

    def test_calcular_qtde_aplicavel_numerico(self):
        linha = LinhaPedido(
            ordem="1",
            codigo="0101001",
            descricao="PECA NUMERICA",
            cor="00100",
            desc_cor="PRETO",
            grade={"4": 200.0, "6": 300.0},
            qtde_total=500.0
        )
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "04"}, linha), 200.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "4"}, linha), 200.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "06"}, linha), 300.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "08"}, linha), 0.0)

    def test_calcular_qtde_aplicavel_sigla_cliente(self):
        linha = LinhaPedido(
            ordem="1",
            codigo="1011033",
            descricao="CONJUNTO MCQUEEN",
            cor="00004",
            desc_cor="MARINHO",
            grade={"2": 3000.0},
            qtde_total=3000.0
        )
        # Faixas de cliente ("RIA", "REN", "YOU") aplicam-se à quantidade total
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "RIA"}, linha), 3000.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "REN"}, linha), 3000.0)
        # Faixa do tamanho 2 aplica-se
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "2"}, linha), 3000.0)
        # Faixas de outros tamanhos (3, 4, 5, 6) não se aplicam
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "3"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "4"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "5"}, linha), 0.0)
        self.assertEqual(_calcular_qtde_aplicavel({"faixa": "6"}, linha), 0.0)



if __name__ == "__main__":
    unittest.main()

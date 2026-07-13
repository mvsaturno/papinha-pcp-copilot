"""
tests/test_engine.py — Golden tests da seção 8 do ROADMAP para o motor de regras.
"""

from __future__ import annotations

import pytest
from datetime import date
from pathlib import Path
import yaml
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.pedido_parser import parse_pedido
from parsers.mrp_parser import parse_mrp
from parsers.capacidade_parser import parse_capacidade
from engine.analise import analisar
from engine.matching import casar_com_mrp
from engine.cronograma import montar_cronograma
from parsers.comum import semana_aass

# Fixtures paths
FIXTURE_PED = Path(__file__).parent / "fixtures" / "pedidos.pdf"
FIXTURE_MRP = Path(__file__).parent / "fixtures" / "mrp.pdf"
FIXTURE_CAP = Path(__file__).parent / "fixtures" / "capacidade.pdf"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "regras.yaml"


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def dados_analise():
    pedidos = parse_pedido(FIXTURE_PED.read_bytes())
    mrp = parse_mrp(FIXTURE_MRP.read_bytes())
    cap = parse_capacidade(FIXTURE_CAP.read_bytes())
    return pedidos, mrp, cap


class TestEngine:

    def test_alertas_globais_capacidade(self, dados_analise, config):
        """
        - Semana 2634 estourada em 11.034 (91.034 − 80.000).
        - Atraso total 17.085 peças (semanas 2619–2627, com hoje=07/07/2026).
        """
        pedidos, mrp, cap = dados_analise
        hoje = date(2026, 7, 7)  # Data do relatório/análise

        res = analisar(pedidos, mrp, cap, hoje, config)

        # Verificar atraso
        # Semanas < 2628 com pendente > 0 no PDF:
        # Ex: semana 2619: 14000, 2623: 3085 -> total = 17085
        alerta_atraso = next((a for a in res.alertas_globais if "atraso" in a.lower()), None)
        assert alerta_atraso is not None
        assert "17.085" in alerta_atraso, f"Got {alerta_atraso}"

        # Verificar semana estourada 2634
        alerta_estouro_2634 = next((a for a in res.alertas_globais if "2634" in a), None)
        assert alerta_estouro_2634 is not None
        assert "11.034" in alerta_estouro_2634, f"Got {alerta_estouro_2634}"

    def test_matching_pedidos_mrp(self, dados_analise, config):
        """Matching: os 6 artigos do pedido casam com as 6 OFs do MRP."""
        pedidos, mrp, cap = dados_analise
        linhas_matched = []
        for p in pedidos:
            for l in p.linhas:
                match = casar_com_mrp(l, mrp, config)
                linhas_matched.append(match)

        ofs = sorted([m.of for m in linhas_matched])
        esperadas = sorted(["263005", "263701", "263702", "263920", "263921", "263922"])
        assert ofs == esperadas

    def test_divergencia_cor_pedido_102559(self, dados_analise, config):
        """Divergência de cor: pedido 102559 (cor 00088) vs MRP (00274) -> gera aviso, NÃO bloqueia."""
        pedidos, mrp, cap = dados_analise
        pedido = next(p for p in pedidos if p.numero == "102559")
        linha = pedido.linhas[0]

        match = casar_com_mrp(linha, mrp, config)
        assert match.confianca == "ALTA"
        
        # O PDF MRP de teste tem a cor correspondente a esta OF como '021216' ou semelhante
        divergencia_msg = next((av for av in match.avisos if "Divergência" in av and "cor" in av.lower()), None)
        assert divergencia_msg is not None
        assert "00088" in divergencia_msg

    def test_pijama_consumo_dobrado(self, dados_analise, config):
        """Pijama: consumo TAG 1.726 ≈ 2×863 -> aviso 'consumo dobrado', confiança média."""
        pedidos, mrp, cap = dados_analise
        pedido = next(p for p in pedidos if p.numero == "94736")  # Pijama
        linha = pedido.linhas[0]

        match = casar_com_mrp(linha, mrp, config)
        # 800 * 1.07 = 856 (arredondado = 856). 1726 ≈ 2 * 856 = 1712 (dentro do limite)
        assert match.confianca == "MEDIA"
        aviso_dobrado = next((av for av in match.avisos if "2x" in av.lower() or "dobrado" in av.lower()), None)
        assert aviso_dobrado is not None

    def test_cronograma_vestido_defaults(self, config):
        """Cronograma VESTIDO com defaults e tecido não localizado (pcp=21): total = 65 dias."""
        # PCP(21) + ENCAIXE(1) + CORTE(6) + COSTURA(15) + QUAL_COSTURA(1) + ESTAMPARIA_NUCA(6) + QUAL_ESTAMPARIA(1) + REVISAO(8) + EMBALAGEM(6) = 65
        hoje = date(2026, 7, 7)
        crono = montar_cronograma("VESTIDO DIANA NEW", None, hoje, config)
        assert crono.rota_detectada == "VESTIDO"
        total_dias = sum(f.dias for f in crono.fases)
        assert total_dias == 65

    def test_veredito_pedido_102622_viavel(self, dados_analise, config):
        """
        Veredito com hoje=07/07/2026, pedido 102622 (entrega 05/10/2026 -> semana 2641, alvo 2639):
        Semana_fim do draft ≈ semana(07/07+65d=10/09) = 2637 <= 2639
        Capacidade 2637 (11.433 + 1.282 <= 80.000) -> VIÁVEL (com ressalvas pela cor/tecido) -> AMARELO ou VERDE.
        """
        pedidos, mrp, cap = dados_analise
        hoje = date(2026, 7, 7)
        res = analisar(pedidos, mrp, cap, hoje, config)

        card = next(c for c in res.pedidos if c.numero_pedido == "102622")
        assert card.veredito in ("AMARELO", "VERDE")
        assert card.semana_alvo == 2639
        assert card.cronograma.semana_fim_aass == 2639
        assert card.capacidade.cabe_no_alvo is True

    def test_veredito_pedido_102559_jit(self, dados_analise, config):
        """
        Pedido 102559 (Regata, entrega 04/11 -> alvo 2643)
        Teste de JIT: fim=23/10/2026 (sexta de 2643), inicio_ideal=19/08/2026, folga ≈ 43 dias.
        """
        pedidos, mrp, cap = dados_analise
        hoje = date(2026, 7, 7)
        res = analisar(pedidos, mrp, cap, hoje, config)

        card = next(c for c in res.pedidos if c.numero_pedido == "102559")
        assert card.semana_alvo == 2643
        assert card.veredito in ("VERDE", "AMARELO")
        
        crono = card.cronograma
        assert crono.semana_fim_aass == 2643
        assert crono.data_fim == date(2026, 10, 23)
        assert crono.inicio_mais_tarde == date(2026, 8, 19)
        assert crono.folga_dias == 43

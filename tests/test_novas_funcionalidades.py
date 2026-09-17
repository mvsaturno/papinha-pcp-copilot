import pytest
from engine.models import LinhaPedido, MatchPedido
from api.setor_adapter import SetorAdapter
from api.mrp_adapter import _calcular_qtde_aplicavel


def test_setor_adapter_lead_times():
    adapter = SetorAdapter()
    assert adapter.obter_lead_time_fase("PCP") == 2
    assert adapter.obter_lead_time_fase("TECELAGEM") == 5
    assert adapter.obter_lead_time_fase("TINTURARIA") == 20
    assert adapter.obter_lead_time_fase("CORTE") == 4
    assert adapter.obter_lead_time_fase("COSTURA") == 11
    assert adapter.obter_lead_time_fase("REVISÃO") == 6
    assert adapter.obter_lead_time_fase("EMBALAGEM") == 4
    assert adapter.obter_lead_time_fase("PCP", pcp_override=10) == 10


def test_calcular_qtde_aplicavel_com_buffer():
    # Pedido com 1000 peças e 1050 peças a produzir (+5% buffer)
    linha = LinhaPedido(
        ordem="1",
        codigo="4104049",
        descricao="VESTIDO",
        cor="0001",
        desc_cor="AZUL",
        qtde_total=1000,
        pecas_produzir=1050,
        grade={"P": 400, "M": 600}
    )

    # Insumo de faixa geral/00 -> deve consumir para 1050 peças
    ins_geral = {"insumo": "03044080", "faixa": "00", "consumo": 0.1}
    qtd_geral = _calcular_qtde_aplicavel(ins_geral, linha)
    assert qtd_geral == 1050.0

    # Insumo de tamanho específico "P" (400 peças nominais -> 420 peças com buffer)
    ins_p = {"insumo": "040594784", "faixa": "P", "consumo": 1.0}
    qtd_p = _calcular_qtde_aplicavel(ins_p, linha)
    assert qtd_p == 420.0

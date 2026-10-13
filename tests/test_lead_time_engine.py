from datetime import date
import pytest
import yaml

from engine.models import LinhaPedido, PendenciaLeadTime, JanelaProducao, Cronograma
from engine.cronograma import montar_cronograma, montar_janela_producao
from api.setor_adapter import gerar_sugestao
from engine.persistencia_lead_time import confirmar


@pytest.fixture
def cfg_padrao():
    return {
        "geral": {
            "buffer_producao_pct": 5,
            "arredondamento": "ceil",
            "semanas_antes_entrega_cliente": 2,
            "semanas_autonomia_pcp": 3,
            "estrategia_cronograma": "jit",
        },
        "rotas": {
            "DEFAULT": ["PCP", "ENCAIXE", "CORTE", "COSTURA", "QUAL_COSTURA", "REVISAO", "EMBALAGEM"],
            "VESTIDO": ["PCP", "ENCAIXE", "CORTE", "COSTURA", "QUAL_COSTURA", "REVISAO", "EMBALAGEM"],
        },
    }


@pytest.fixture
def linha_simples():
    """Linha sem código cadastrado no Excia: usa a rota interna de regras.yaml"""
    return LinhaPedido(
        ordem="1",
        codigo="",
        descricao="VESTIDO INFANTIL",
        cor="0001",
        desc_cor="ROSA",
        grade={"P": 100.0},
        qtde_total=100.0,
    )


@pytest.fixture
def linha_real_l13():
    """Linha com código 01463009 com fluxo real L13 mapeado na fixture do Excia"""
    return LinhaPedido(
        ordem="1",
        codigo="01463009",
        descricao="VESTIDO MEIA MALHA",
        cor="0001",
        desc_cor="ROSA",
        grade={"P": 100.0},
        qtde_total=100.0,
    )


def test_montar_cronograma_incompleto_retorna_pendencia(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
    # Nenhum lead time informado
    res = montar_cronograma(linha_simples, None, hoje, cfg_padrao, lead_times_informados={})

    assert isinstance(res, PendenciaLeadTime)
    assert len(res.setores_faltantes) > 0
    # Setores da rota VESTIDO devem estar entre os faltantes
    assert "CORTE" in res.setores_faltantes
    assert "COSTURA" in res.setores_faltantes
    assert "REVISAO" in res.setores_faltantes
    assert "EMBALAGEM" in res.setores_faltantes

    # As sugestões devem ser preenchidas para cada setor faltante
    assert "CORTE" in res.sugestoes
    assert res.sugestoes["CORTE"].dias_min > 0
    assert res.sugestoes["CORTE"].origem in ("generico", "ultimo_confirmado")


def test_montar_cronograma_completo_calcula_sucesso(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
    lts = {
        "PCP": 2,
        "ENCAIXE": 1,
        "CORTE": 4,
        "COSTURA": 11,
        "QUAL_COSTURA": 1,
        "REVISAO": 6,
        "EMBALAGEM": 4,
    }
    res = montar_cronograma(linha_simples, None, hoje, cfg_padrao, lead_times_informados=lts)

    assert isinstance(res, Cronograma)
    assert len(res.fases) == 7
    assert res.data_fim is not None
    assert res.semana_fim_aass > 0
    # Verifica duração da fase corte
    fase_corte = next(f for f in res.fases if f.nome == "CORTE")
    assert fase_corte.dias == 4


def test_montar_janela_producao_caso_degenerado(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
    # Valores pontuais min == max
    lts = {
        "PCP": (2, 2),
        "ENCAIXE": (1, 1),
        "CORTE": (4, 4),
        "COSTURA": (11, 11),
        "QUAL_COSTURA": (1, 1),
        "REVISAO": (6, 6),
        "EMBALAGEM": (4, 4),
    }
    janela = montar_janela_producao(linha_simples, None, hoje, cfg_padrao, lead_times_informados=lts)

    assert isinstance(janela, JanelaProducao)
    # No caso degenerado, semana_w == semana_z
    assert janela.semana_w == janela.semana_z
    assert janela.cenario_otimista.data_fim == janela.cenario_pessimista.data_fim
    assert len(janela.cenario_otimista.fases) == len(janela.cenario_pessimista.fases)


def test_montar_janela_producao_com_faixas(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
    # Faixas de variação reais
    lts = {
        "PCP": (2, 5),
        "ENCAIXE": (1, 2),
        "CORTE": (3, 6),
        "COSTURA": (10, 15),
        "QUAL_COSTURA": (1, 2),
        "REVISAO": (5, 8),
        "EMBALAGEM": (3, 5),
    }
    janela = montar_janela_producao(linha_simples, None, hoje, cfg_padrao, lead_times_informados=lts)

    assert isinstance(janela, JanelaProducao)
    # Cenário pessimista deve terminar depois ou igual ao otimista
    assert janela.cenario_pessimista.data_fim > janela.cenario_otimista.data_fim
    assert janela.semana_z >= janela.semana_w


def test_montar_cronograma_fluxo_real_l13(linha_real_l13, cfg_padrao):
    hoje = date(2026, 10, 13)
    # Primeiro verifica que sem informar tudo, detecta setores faltantes do fluxo L13
    res_pend = montar_cronograma(linha_real_l13, None, hoje, cfg_padrao, lead_times_informados={"CORTE": 4})
    assert isinstance(res_pend, PendenciaLeadTime)
    assert "TECELAGEM" in res_pend.setores_faltantes
    assert "TINTURARIA" in res_pend.setores_faltantes

    # Agora informamos todos os setores através das sugestões geradas
    lts_completos = {setor: (sug.dias_min, sug.dias_max) for setor, sug in res_pend.sugestoes.items()}
    lts_completos["CORTE"] = (4, 4)

    res_ok = montar_cronograma(linha_real_l13, None, hoje, cfg_padrao, lead_times_informados=lts_completos)
    assert isinstance(res_ok, Cronograma)
    assert len(res_ok.fases) > 0
    assert res_ok.semana_fim_aass > 0


def test_gerar_sugestao_prioridades(tmp_path):
    db_teste = tmp_path / "test_sugestoes.sqlite"
    yaml_teste = tmp_path / "test_sugestoes.yaml"

    yaml_conteudo = {
        "setores": {
            "TINTURARIA": [18, 20],
            "CORTE": [4, 4],
        }
    }
    with open(yaml_teste, "w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_conteudo, f)

    # 1. Sem histórico, cai para yaml genérico
    sug_gen = gerar_sugestao("99999", "TINTURARIA", db_path=db_teste, yaml_path=yaml_teste)
    assert sug_gen.origem == "generico"
    assert sug_gen.dias_min == 18
    assert sug_gen.dias_max == 20

    # 2. Com confirmação no SQLite, prevalece último confirmado
    hoje = date(2026, 10, 13)
    confirmar("99999", "TINTURARIA", dias_min=15, dias_max=17, confirmado_por="alexandre", db_path=db_teste, data_confirmacao=hoje)

    sug_hist = gerar_sugestao("99999", "TINTURARIA", db_path=db_teste, yaml_path=yaml_teste)
    assert sug_hist.origem == "ultimo_confirmado"
    assert sug_hist.dias_min == 15
    assert sug_hist.dias_max == 17
    assert sug_hist.confirmado_em == hoje

    # 3. Setor não cadastrado em lugar nenhum
    sug_none = gerar_sugestao("99999", "SETOR_INEXISTENTE_XYZ", db_path=db_teste, yaml_path=yaml_teste)
    assert sug_none.origem == "sem_sugestao"
    assert sug_none.dias_min == 0
    assert sug_none.dias_max == 0

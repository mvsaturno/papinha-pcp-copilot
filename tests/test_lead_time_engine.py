from datetime import date
from unittest.mock import patch, MagicMock
import pytest
import yaml

from engine.models import (
    LinhaPedido,
    Pedido,
    MatchPedido,
    MatchInsumo,
    CapacidadeSemanal,
    PendenciaLeadTime,
    JanelaProducao,
    Cronograma,
)
from engine.cronograma import montar_cronograma, montar_janela_producao
from engine.orquestrador import analisar_pedido_por_numero
from api.setor_adapter import gerar_sugestao
from engine.persistencia_lead_time import confirmar


@pytest.fixture
def cfg_padrao():
    with open("config/regras.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


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


# ─────────────────────────────────────────────────────────────────────────────
# PROBLEMA 1 — Produção sem lead_times_informados usa sugestão automática
# ─────────────────────────────────────────────────────────────────────────────

def test_montar_cronograma_sem_informados_usa_sugestoes_automaticas(linha_simples, cfg_padrao):
    """
    Cenário atual de produção: lead_times_informados não é passado.
    O cronograma deve ser calculado com sucesso usando as sugestões automáticas,
    sem retornar PendenciaLeadTime, mas marcando lead_time_sugerido_nao_confirmado = True.
    """
    hoje = date(2026, 10, 13)
    res = montar_cronograma(linha_simples, None, hoje, cfg_padrao, lead_times_informados={})

    assert isinstance(res, Cronograma)
    assert res.data_fim is not None
    assert res.semana_fim_aass > 0
    assert res.lead_time_sugerido_nao_confirmado is True
    assert len(res.etapas_sugeridas) > 0
    assert "CORTE" in res.etapas_sugeridas
    assert "COSTURA" in res.etapas_sugeridas


def test_montar_cronograma_sem_sugestao_retorna_pendencia_real(linha_simples):
    """
    PendenciaLeadTime só deve ser devolvida quando genuinamente não houver
    nenhuma sugestão disponível para a etapa (origem='sem_sugestao', dias=0).
    """
    hoje = date(2026, 10, 13)
    cfg_com_etapa_desconhecida = {
        "rotas": {
            "DEFAULT": ["PCP", "ETAPA_INEXISTENTE_SEM_CADASTRO_XYZ"],
            "VESTIDO": ["PCP", "ETAPA_INEXISTENTE_SEM_CADASTRO_XYZ"],
        },
        "geral": {},
    }
    res = montar_cronograma(linha_simples, None, hoje, cfg_com_etapa_desconhecida, lead_times_informados={})

    assert isinstance(res, PendenciaLeadTime)
    assert "ETAPA_INEXISTENTE_SEM_CADASTRO_XYZ" in res.setores_faltantes
    assert res.sugestoes["ETAPA_INEXISTENTE_SEM_CADASTRO_XYZ"].origem == "sem_sugestao"


def test_regressao_producao_analisar_pedido_sem_lead_times_informados(linha_real_l13, cfg_padrao):
    """
    Validação 1 obrigatória: chamar analisar_pedido_por_numero(numero, CONFIG)
    sem nenhum lead_times_informados (como app.py faz hoje) e assertar que
    produz cronograma válido e aviso explícito de sugestão não confirmada.
    """
    with patch("engine.orquestrador.PedidoAdapter") as mock_ped_cls, \
         patch("engine.orquestrador.CapacidadeAdapter") as mock_cap_cls, \
         patch("engine.orquestrador.MrpAdapter") as mock_mrp_cls:

        mock_ped = Pedido(
            numero="107487",
            ped_cliente="PED-107487",
            emissao=date(2026, 9, 1),
            entrega=date(2026, 11, 20),
            cliente="CLIENTE TESTE",
            colecao="VERAO",
            linhas=[linha_real_l13],
        )
        mock_ped_cls.return_value.buscar_pedido.return_value = mock_ped

        mock_cap = CapacidadeSemanal(
            periodos={2645: 5000, 2646: 5000, 2647: 5000},
        )
        mock_cap_cls.return_value.buscar_capacidade.return_value = mock_cap

        mock_mrp_cls.return_value.explodir_mrp.return_value = [
            MatchInsumo(
                cod_insumo="01.001",
                descricao="MALHA 100% ALGODAO",
                un="KG",
                cod_cor="01",
                nome_cor="BRANCO",
                necessario=10.0,
                aloc_estoque=100.0,
                aloc_compra=0.0,
                aloc_tecelagem=0.0,
                aloc_pend_tint=0.0,
                aloc_tinturaria=0.0,
                saldo=90.0,
                status="OK_ESTOQUE",
            )
        ]

        resultado = analisar_pedido_por_numero("107487", cfg_padrao)

        assert len(resultado.pedidos) == 1
        card = resultado.pedidos[0]
        # Cronograma válido gerado
        assert card.cronograma is not None
        assert card.pendencia_lead_time is None
        # Veredito não é travado em AMARELO forçado por falta de chat
        assert card.veredito in ("VERDE", "AMARELO", "VERMELHO")
        # Aviso visível de lead times sugeridos
        assert card.lead_time_sugerido_nao_confirmado is True
        assert "LEAD_TIME_SUGERIDO_NAO_CONFIRMADO" in card.avisos_flags
        assert any("Lead time de" in m and "não confirmado" in m for m in card.motivos)


# ─────────────────────────────────────────────────────────────────────────────
# PROBLEMA 2 — Cálculo dinâmico de PCP pelo MRP e soberania do analista
# ─────────────────────────────────────────────────────────────────────────────

def test_problema_2_calculo_dinamico_pcp_mrp_falta(linha_simples, cfg_padrao):
    """
    Validação 2 obrigatória: um match com insumo em status 'FALTA'
    deve produzir pcp_dias igual a compra (7) + tecelagem (7) + tinturaria (14) = 28 dias,
    não o valor fixo 2.
    """
    hoje = date(2026, 10, 13)
    insumo_falta = MatchInsumo(
        cod_insumo="TEC01",
        descricao="MALHA COTTON 100%",
        un="KG",
        cod_cor="01",
        nome_cor="BRANCO",
        necessario=10.0,
        aloc_estoque=0.0,
        aloc_compra=0.0,
        aloc_tecelagem=0.0,
        aloc_pend_tint=0.0,
        aloc_tinturaria=0.0,
        saldo=-10.0,
        status="FALTA",
    )
    match_falta = MatchPedido(
        cod_artigo="01463009",
        of="000001",
        confianca="ALTA",
        insumos=[insumo_falta],
        tecido_principal_encontrado=True,
    )

    # 1. Sem valor informado para PCP -> cálculo dinâmico pelo MRP dá 28 dias
    res = montar_cronograma(linha_simples, match_falta, hoje, cfg_padrao)
    assert isinstance(res, Cronograma)
    assert res.pcp_dias == 28
    fase_pcp = next(f for f in res.fases if f.nome == "PCP")
    assert fase_pcp.dias == 28

    # 2. Quando analista informa explicitamente PCP no chat -> prevalece sobre o cálculo do MRP
    res_inf = montar_cronograma(linha_simples, match_falta, hoje, cfg_padrao, lead_times_informados={"PCP": 5})
    assert isinstance(res_inf, Cronograma)
    assert res_inf.pcp_dias == 5
    fase_pcp_inf = next(f for f in res_inf.fases if f.nome == "PCP")
    assert fase_pcp_inf.dias == 5


# ─────────────────────────────────────────────────────────────────────────────
# PROBLEMA 3 — Correspondência estritamente exata (sem substring)
# ─────────────────────────────────────────────────────────────────────────────

def test_problema_3_substring_matching_independencia_setores(linha_simples, cfg_padrao):
    """
    Validação 3 obrigatória: dois setores cujo nome normalizado é substring um do outro
    (ex. 'COSTURA' e 'QUAL_COSTURA') devem ser tratados como etapas independentes.
    Informar COSTURA = 15 NÃO pode contaminar QUAL_COSTURA.
    """
    hoje = date(2026, 10, 13)
    lts = {"COSTURA": 15}
    res = montar_cronograma(linha_simples, None, hoje, cfg_padrao, lead_times_informados=lts)

    assert isinstance(res, Cronograma)
    fase_costura = next(f for f in res.fases if f.nome == "COSTURA")
    fase_qual_costura = next(f for f in res.fases if f.nome == "QUAL_COSTURA")

    # COSTURA usa o valor informado
    assert fase_costura.dias == 15
    assert "COSTURA" not in res.etapas_sugeridas

    # QUAL_COSTURA NÃO herdou 15! Usa sua própria sugestão (1 dia)
    assert fase_qual_costura.dias == 1
    assert "QUAL_COSTURA" in res.etapas_sugeridas


# ─────────────────────────────────────────────────────────────────────────────
# Testes Adicionais e Janela de Produção
# ─────────────────────────────────────────────────────────────────────────────

def test_montar_cronograma_completo_calcula_sucesso(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
    lts = {
        "PCP": 2,
        "ENCAIXE": 1,
        "CORTE": 4,
        "COSTURA": 11,
        "QUAL_COSTURA": 1,
        "ESTAMPARIA_NUCA": 4,
        "QUAL_ESTAMPARIA": 1,
        "REVISAO": 6,
        "EMBALAGEM": 4,
    }
    res = montar_cronograma(linha_simples, None, hoje, cfg_padrao, lead_times_informados=lts)

    assert isinstance(res, Cronograma)
    assert len(res.fases) == 9
    assert res.data_fim is not None
    assert res.semana_fim_aass > 0
    # Todas as etapas foram informadas -> flag deve ser False
    assert res.lead_time_sugerido_nao_confirmado is False
    assert len(res.etapas_sugeridas) == 0

    fase_corte = next(f for f in res.fases if f.nome == "CORTE")
    assert fase_corte.dias == 4


def test_montar_janela_producao_caso_degenerado(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
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
    assert janela.semana_w == janela.semana_z
    assert janela.cenario_otimista.data_fim == janela.cenario_pessimista.data_fim
    assert len(janela.cenario_otimista.fases) == len(janela.cenario_pessimista.fases)


def test_montar_janela_producao_com_faixas(linha_simples, cfg_padrao):
    hoje = date(2026, 10, 13)
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
    assert janela.cenario_pessimista.data_fim > janela.cenario_otimista.data_fim
    assert janela.semana_z >= janela.semana_w


def test_montar_cronograma_fluxo_real_l13(linha_real_l13, cfg_padrao):
    hoje = date(2026, 10, 13)
    # Com CORTE informado, as outras 27 etapas do fluxo L13 usam sugestões
    res_parcial = montar_cronograma(linha_real_l13, None, hoje, cfg_padrao, lead_times_informados={"CORTE": 4})
    assert isinstance(res_parcial, Cronograma)
    assert res_parcial.lead_time_sugerido_nao_confirmado is True
    fase_corte = next(f for f in res_parcial.fases if f.nome == "CORTE")
    assert fase_corte.dias == 4


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

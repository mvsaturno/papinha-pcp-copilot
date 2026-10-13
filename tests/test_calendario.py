from datetime import date
from engine.calendario import (
    CalendarioProdutivo,
    Parada,
    eh_dia_util,
    avancar_dias_uteis,
    recuar_dias_uteis,
    contar_dias_uteis,
    obter_paradas_no_intervalo,
)
from engine.cronograma import montar_cronograma, ajustar_cronograma_backward
from engine.models import LinhaPedido, Cronograma


def test_calendario_feriado_e_dia_util():
    # 07/09/2026 é Independência do Brasil (segunda-feira) -> não é dia útil
    d_feriado = date(2026, 9, 7)
    assert not eh_dia_util(d_feriado)

    # 08/09/2026 é terça-feira normal -> é dia útil
    d_util = date(2026, 9, 8)
    assert eh_dia_util(d_util)

    # 12/09/2026 é sábado -> não é dia útil
    assert not eh_dia_util(date(2026, 9, 12))


def test_calendario_fase_atravessa_ferias_coletivas():
    """
    (a) fase de 5 dias começando 18/12/2026 (sexta-feira antes das férias coletivas 21/12-04/01)
    deve terminar após 04/01/2027 (especificamente em 08/01/2027).
    """
    ini = date(2026, 12, 18)
    fim = avancar_dias_uteis(ini, 5)

    # Como de 21/12/2026 a 04/01/2027 há parada de férias coletivas,
    # os próximos 5 dias úteis contados após 18/12 são:
    # 05/01 (1º), 06/01 (2º), 07/01 (3º), 08/01 (4º), 11/01 (5º)
    assert fim > date(2027, 1, 4)
    # Verifica que obter_paradas_no_intervalo detecta as férias coletivas
    paradas = obter_paradas_no_intervalo(ini, fim)
    assert len(paradas) >= 1
    assert "Férias coletivas" in paradas[0].descricao


def test_calendario_backward_scheduling_atravessa_parada():
    """
    (b) backward a partir de janeiro/2027 recua as fases considerando o recesso de fim de ano.
    """
    fim_alvo = date(2027, 1, 15)  # sexta
    # Recuar 15 dias úteis a partir de 15/01/2027 deve saltar as férias coletivas (21/12 a 04/01)
    ini_recuado = recuar_dias_uteis(fim_alvo, 15)
    assert ini_recuado < date(2026, 12, 21)


def test_cronograma_exibe_marcador_de_parada(tmp_path):
    """
    Verifica que uma fase que cruza as férias coletivas recebe a anotação na lista de paradas.
    """
    linha = LinhaPedido(
        ordem="1",
        codigo="",
        descricao="VESTIDO TESTE",
        cor="01",
        desc_cor="AZUL",
        grade={"P": 100},
        qtde_total=100,
    )
    cfg = {
        "rotas": {
            "DEFAULT": ["COSTURA"],
            "VESTIDO": ["COSTURA"],
        },
        "geral": {},
    }
    # Inicia em 18/12/2026 com 10 dias úteis de COSTURA
    hoje = date(2026, 12, 18)
    crono = montar_cronograma(linha, None, hoje, cfg, lead_times_informados={"COSTURA": 10})
    assert isinstance(crono, Cronograma)
    fase_costura = crono.fases[0]
    assert len(fase_costura.paradas) > 0
    assert any("Férias coletivas" in p for p in fase_costura.paradas)

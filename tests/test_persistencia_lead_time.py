from datetime import date
from engine.persistencia_lead_time import buscar_ultimo, confirmar


def test_persistencia_lead_time_ciclo_completo(tmp_path):
    db_test = tmp_path / "test_lead_times.sqlite"

    # 1. Busca sem histórico
    sug_ini = buscar_ultimo("01463009", "TECELAGEM", db_path=db_test)
    assert sug_ini is None

    # 2. Confirmação inicial
    hoje = date(2026, 10, 13)
    confirmar("01463009", "TECELAGEM", dias_min=4, dias_max=6, confirmado_por="marcos", db_path=db_test, data_confirmacao=hoje)

    sug = buscar_ultimo("01463009", "TECELAGEM", db_path=db_test)
    assert sug is not None
    assert sug.dias_min == 4
    assert sug.dias_max == 6
    assert sug.origem == "ultimo_confirmado"
    assert sug.confirmado_em == hoje

    # 3. UPSERT com novos valores (soberano)
    amanha = date(2026, 10, 14)
    confirmar("01463009", "TECELAGEM", dias_min=5, dias_max=5, confirmado_por="alexandre", db_path=db_test, data_confirmacao=amanha)

    sug_atualizada = buscar_ultimo("01463009", "TECELAGEM", db_path=db_test)
    assert sug_atualizada is not None
    assert sug_atualizada.dias_min == 5
    assert sug_atualizada.dias_max == 5
    assert sug_atualizada.confirmado_em == amanha

    # 4. Outro setor do mesmo artigo não deve ser afetado
    sug_outro = buscar_ultimo("01463009", "TINTURARIA", db_path=db_test)
    assert sug_outro is None

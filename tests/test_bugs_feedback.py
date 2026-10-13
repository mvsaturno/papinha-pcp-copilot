"""
tests/test_bugs_feedback.py — Testes unitários para os bugs do feedback do gestor (A3 a A8).
Conforme Sprint 5 e Sprint 6 / ROADMAP e REVISAO_FEEDBACK_GESTOR_2026-09.md.
"""

import unittest
from datetime import date

from engine.models import (
    BlocoInsumo,
    CapacidadeSemanal,
    FaseCronograma,
    LinhaPedido,
    MatchInsumo,
    MatchPedido,
    Pedido,
    ProdutoMRP,
)
from engine.analise import _decidir_veredito, _montar_sugestao
from engine.capacidade import verificar_capacidade_pedido
from engine.calendario import carregar_calendario, contar_dias_uteis, avancar_dias_uteis
from engine.insumos import avaliar_insumos, _e_bloqueante
from engine.matching import casar_com_mrp
from parsers.comum import (
    semanas_entre,
    aass_add,
    quarta_da_semana,
    sexta_da_semana,
)


class TestBugsFeedbackA3(unittest.TestCase):
    """
    A3: Contagem de dias coerente com as datas exibidas.
    Garante que a duração em dias úteis entre início e fim de cada fase do cronograma
    bate exatamente com o cálculo de dias úteis pelo calendário da aplicação.
    """
    def setUp(self):
        self.cal = carregar_calendario()

    def test_contagem_dias_sem_feriado(self):
        # 5 dias úteis a partir de 01/10/2026 (qui)
        ini = date(2026, 10, 1)
        fim = avancar_dias_uteis(ini, 5) # sex(2), seg(5), ter(6), qua(7), qui(8)
        self.assertEqual(fim, date(2026, 10, 8))
        dias_uteis = contar_dias_uteis(ini, fim)
        self.assertEqual(dias_uteis, 5)

    def test_contagem_dias_com_feriado(self):
        # Período que atravessa 07/09/2026 (Independência)
        ini = date(2026, 9, 3) # quinta
        fim = avancar_dias_uteis(ini, 3) # sex(4), feriado(7), ter(8), qua(9)
        self.assertEqual(fim, date(2026, 9, 9))
        dias_uteis = contar_dias_uteis(ini, fim)
        self.assertEqual(dias_uteis, 3)

    def test_contagem_dias_com_parada_ferias_coletivas(self):
        # Período que atravessa férias coletivas (21/12/2026 a 04/01/2027)
        ini = date(2026, 12, 18) # sexta
        fim = avancar_dias_uteis(ini, 2) # ter(05/01), qua(06/01)
        self.assertEqual(fim, date(2027, 1, 6))
        dias_uteis = contar_dias_uteis(ini, fim)
        self.assertEqual(dias_uteis, 2)


class TestBugsFeedbackA4(unittest.TestCase):
    """
    A4: Sugestão explícita: semana de produção + nova entrega a propor ao comercial.
    """
    def setUp(self):
        self.cfg = {
            "geral": {
                "semanas_autonomia_pcp": 3,
                "semanas_entre_producao_e_entrega": 1,
                "semanas_maximo_sem_autorizacao": 2,
            }
        }

    def test_sugestao_inviavel_formato_e_datas_com_of(self):
        # Cenário do pedido 107487: entrega 25/01/2027 -> alvo 2702; sugerida 2704 com OF emitida
        # Quarta da semana 2704 é 27/01/2027. Nova entrega na semana 2705 é 05/02/2027 (sexta).
        sug = _montar_sugestao(
            semana_sug=2704,
            semana_alvo=2702,
            entrega=date(2027, 1, 25),
            cfg=self.cfg,
            of_emitida=True,
        )
        self.assertIn("Semana alvo 2702 não atende", sug)
        self.assertIn("Produção sugerida: semana 2704", sug)
        self.assertIn("27/01/2027", sug)  # Quarta-feira, igual ao cronograma da OF
        self.assertIn("Nova entrega a propor ao comercial: semana 2705", sug)
        self.assertIn("05/02/2027", sug)  # Sexta-feira da semana 2705

    def test_sugestao_viavel_formato_pre_of(self):
        # Simulação pré-OF: produção na sexta-feira
        sug = _montar_sugestao(
            semana_sug=2640,
            semana_alvo=2640,
            entrega=date(2026, 10, 16),
            cfg=self.cfg,
            of_emitida=False,
        )
        sexta = sexta_da_semana(2640).strftime("%d/%m/%Y")
        self.assertIn("✅ Produzir na semana 2640", sug)
        self.assertIn(f"termina {sexta}", sug)
        self.assertIn("entrega ao cliente mantida", sug)


class TestBugsFeedbackA5(unittest.TestCase):
    """
    A5: Aritmética de semanas na virada de ano usando semanas_entre e aass_add.
    """
    def setUp(self):
        self.cfg = {
            "geral": {
                "semanas_autonomia_pcp": 3,
                "semanas_entre_producao_e_entrega": 1,
                "semanas_maximo_sem_autorizacao": 2,
            },
            "capacidade": {
                "limite_total_semana": 80000,
                "ociosidade_alerta_pct": 40,
            }
        }

    def test_virada_de_ano_semanas_entre(self):
        # 2702 e 2652 (ano 2026 tem 53 semanas ISO):
        # 2652 -> 2653 (1 sem) -> 2701 (2 sem) -> 2702 (3 sem)
        diff = semanas_entre(2702, 2652)
        self.assertEqual(diff, 3)

        diff_inv = semanas_entre(2652, 2702)
        self.assertEqual(diff_inv, -3)

    def test_decidir_veredito_virada_de_ano_dentro_da_autonomia(self):
        # Alvo 2702, sugerida 2652 (3 semanas antes) -> dentro da autonomia de 3 semanas -> VERDE
        pedido = Pedido(numero="107487", ped_cliente="", emissao=date(2026, 9, 1), entrega=date(2027, 1, 25), cliente="", colecao="")
        linha = LinhaPedido(ordem="1", codigo="123", descricao="CONJUNTO", cor="01", desc_cor="PRETO", grade={"P": 1000}, qtde_total=1000)
        match = MatchPedido(cod_artigo="123", of="OF1", confianca="ALTA")
        # Semanas 2702, 2701 e 2653 cheias, 2652 com capacidade livre
        cap = CapacidadeSemanal(periodos={2702: 80000, 2701: 80000, 2653: 80000, 2652: 10000})

        analise_cap = verificar_capacidade_pedido(
            semana_alvo=2702,
            qtd_of=1000,
            cap=cap,
            cfg=self.cfg,
            semana_minima=2650,
        )
        self.assertEqual(analise_cap.semana_sugerida, 2652)

        veredito, motivos, sugestao, semana_sug = _decidir_veredito(
            pedido=pedido,
            linha=linha,
            match=match,
            cronograma=None,
            insumos=[],
            analise_cap=analise_cap,
            semana_alvo=2702,
            semana_minima=2650,
            qtd_of=1000,
            cap=cap,
            cfg=self.cfg,
        )
        self.assertEqual(veredito, "VERDE")
        self.assertTrue(any("Antecipação de 3 sem., dentro da autonomia" in m for m in motivos))

    def test_decidir_veredito_virada_de_ano_fora_da_autonomia(self):
        # Alvo 2702, sugerida 2650 (5 semanas antes) -> excede autonomia de 3 semanas -> AMARELO com autorização
        pedido = Pedido(numero="107487", ped_cliente="", emissao=date(2026, 9, 1), entrega=date(2027, 1, 25), cliente="", colecao="")
        linha = LinhaPedido(ordem="1", codigo="123", descricao="CONJUNTO", cor="01", desc_cor="PRETO", grade={"P": 1000}, qtde_total=1000)
        match = MatchPedido(cod_artigo="123", of="OF1", confianca="ALTA")
        # Sem capacidade entre 2651 e 2703, primeira viável em 2650
        cap = CapacidadeSemanal(periodos={
            2703: 85000, 2702: 85000, 2701: 85000, 2653: 85000, 2652: 85000, 2651: 85000, 2650: 5000
        })

        analise_cap = verificar_capacidade_pedido(
            semana_alvo=2702,
            qtd_of=1000,
            cap=cap,
            cfg=self.cfg,
            semana_minima=2645,
        )
        self.assertEqual(analise_cap.semana_sugerida, 2650)

        veredito, motivos, sugestao, semana_sug = _decidir_veredito(
            pedido=pedido,
            linha=linha,
            match=match,
            cronograma=None,
            insumos=[],
            analise_cap=analise_cap,
            semana_alvo=2702,
            semana_minima=2645,
            qtd_of=1000,
            cap=cap,
            cfg=self.cfg,
        )
        self.assertEqual(veredito, "AMARELO")
        self.assertTrue(any("REQUER AUTORIZAÇÃO DA GESTÃO" in m for m in motivos))

    def test_janela_autonomia_populada_em_analise_capacidade(self):
        cap = CapacidadeSemanal(periodos={2702: 10000})
        analise_cap = verificar_capacidade_pedido(
            semana_alvo=2702,
            qtd_of=1000,
            cap=cap,
            cfg=self.cfg,
            semana_minima=2640,
        )
        self.assertIn("inicio", analise_cap.janela_autonomia)
        self.assertIn("fim", analise_cap.janela_autonomia)
        self.assertEqual(analise_cap.janela_autonomia["fim"], 2702)
        self.assertEqual(analise_cap.janela_autonomia["inicio"], aass_add(2702, -3))


class TestBugsFeedbackA6(unittest.TestCase):
    """
    A6: Insumo em FALTA: parar de inventar 'disponível em' para malha.
    """
    def setUp(self):
        self.cfg = {
            "lead_times_estoque_futuro_dias": {
                "compra": 7,
                "tecelagem": 7,
                "tinturaria": 14,
                "pend_tinturaria": 14,
            },
            "insumo_fase_consumo": {},
            "fase_consumo_default": "CORTE",
        }
        self.hoje = date(2026, 9, 15)

    def test_malha_sem_crua_sem_previsao_sem_data(self):
        ins = MatchInsumo(
            cod_insumo="03008234",
            descricao="MALHA TESTE PRETA",
            un="KG",
            cod_cor="001",
            nome_cor="PRETO",
            necessario=300.0,
            aloc_estoque=0.0,
            aloc_compra=0.0,
            aloc_tecelagem=0.0,
            aloc_pend_tint=0.0,
            aloc_tinturaria=0.0,
            saldo=-300.0,
            cascata_info={"tem_crua": False, "saldo_crua": 0.0, "necessita_tecelagem_fio": True},
        )
        avaliar_insumos([ins], None, self.hoje, self.cfg)

        self.assertEqual(ins.status, "FALTA")
        self.assertEqual(ins.previsao_tipo, "SEM_PREVISAO")
        self.assertIsNone(ins.disponivel_em)
        self.assertIn("necessita tecelagem (7 d) + tinturaria (14 d) = 21 dias úteis", ins.previsao_detalhe)

    def test_malha_com_crua_suficiente_estimativa_tinturaria(self):
        ins = MatchInsumo(
            cod_insumo="03008234",
            descricao="MALHA TESTE PRETA",
            un="KG",
            cod_cor="001",
            nome_cor="PRETO",
            necessario=300.0,
            aloc_estoque=0.0,
            aloc_compra=0.0,
            aloc_tecelagem=0.0,
            aloc_pend_tint=0.0,
            aloc_tinturaria=0.0,
            saldo=-300.0,
            cascata_info={"tem_crua": True, "saldo_crua": 500.0, "atende_via_tinturaria": True},
        )
        avaliar_insumos([ins], None, self.hoje, self.cfg)

        self.assertEqual(ins.status, "FALTA")
        self.assertEqual(ins.previsao_tipo, "ESTIMATIVA")
        self.assertIsNotNone(ins.disponivel_em)
        self.assertIn("tinturaria da malha crua em estoque", ins.previsao_detalhe)

    def test_aviamento_falta_estimativa_compra(self):
        ins = MatchInsumo(
            cod_insumo="08001234",
            descricao="BOTAO MADREPEROLA",
            un="UN",
            cod_cor="001",
            nome_cor="BRANCO",
            necessario=100.0,
            aloc_estoque=0.0,
            aloc_compra=0.0,
            aloc_tecelagem=0.0,
            aloc_pend_tint=0.0,
            aloc_tinturaria=0.0,
            saldo=-100.0,
        )
        avaliar_insumos([ins], None, self.hoje, self.cfg)

        self.assertEqual(ins.status, "FALTA")
        self.assertEqual(ins.previsao_tipo, "ESTIMATIVA")
        self.assertIsNotNone(ins.disponivel_em)
        self.assertIn("estimativa de compra", ins.previsao_detalhe)

    def test_e_bloqueante_normalizacao_aliases(self):
        # Fase no cronograma: "QUAL. ESTAMPARIA", insumo consome em "QUAL_ESTAMPARIA"
        from engine.models import Cronograma
        crono = Cronograma(
            fases=[
                FaseCronograma(nome="QUAL. ESTAMPARIA", inicio=date(2026, 9, 20), fim=date(2026, 9, 21), dias=1),
                FaseCronograma(nome="ESTAMPA NUCA", inicio=date(2026, 9, 22), fim=date(2026, 9, 25), dias=4),
            ],
            rota_detectada="DEFAULT",
            pcp_dias=2,
            data_fim=date(2026, 9, 25),
            semana_fim_aass=2639,
        )
        ins1 = MatchInsumo(
            cod_insumo="1", descricao="TINTA", un="UN", cod_cor="1", nome_cor="X",
            necessario=10, aloc_estoque=0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0,
            status="OK_FUTURO", disponivel_em=date(2026, 9, 25), fase_consumo="QUAL_ESTAMPARIA"
        )
        # Como disponivel_em (25/09) > fase.inicio (20/09), deve ser bloqueante!
        self.assertTrue(_e_bloqueante(ins1, crono))

        ins2 = MatchInsumo(
            cod_insumo="2", descricao="TRANSFER", un="UN", cod_cor="1", nome_cor="X",
            necessario=10, aloc_estoque=0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0,
            status="OK_FUTURO", disponivel_em=date(2026, 9, 18), fase_consumo="ESTAMPARIA_NUCA"
        )
        # Como disponivel_em (18/09) < fase.inicio (22/09), NÃO deve ser bloqueante!
        self.assertFalse(_e_bloqueante(ins2, crono))


class TestBugsFeedbackA7eA8(unittest.TestCase):
    """
    A7: Agrupamento de ProdutoMRP do mesmo (cod_insumo, cod_cor) somando consumo.
    A8: Remoção de falso positivo 'Cor Divergente' via API.
    """
    def setUp(self):
        self.cfg = {
            "geral": {
                "buffer_producao_pct": 5,
                "tolerancia_match_qtd_pct": 15,
                "arredondamento": "ceil",
            },
            "tecido_principal_keywords": ["MALHA", "RIBANA"],
        }
        self.linha = LinhaPedido(
            ordem="1",
            codigo="4104049",
            descricao="REGATA TESTE",
            cor="00001",
            desc_cor="PRETO",
            grade={"P": 1000},
            qtde_total=1000,
        )

    def test_agrupamento_mesmo_insumo_e_cor(self):
        # 3 linhas da ficha técnica com o mesmo insumo 03008234 e cor 00001
        bloco = BlocoInsumo(
            cod_insumo="03008234",
            descricao="MALHA TINTA PT",
            un="KG",
            cod_cor="00001",
            nome_cor="PRETO",
            consumo=317.25,
            estoque=0.0,
            compra=0.0,
            tecelagem=0.0,
            pend_tint=0.0,
            tinturaria=0.0,
            saldo=-317.25,
            origem_api=True,
        )
        prod1 = ProdutoMRP(of="OF1", cod_artigo="4104049", descricao="REGATA", setor_atual="CORTE", consumo=305.0,
                           aloc_estoque=0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0, origem_api=True)
        prod2 = ProdutoMRP(of="OF1", cod_artigo="4104049", descricao="REGATA", setor_atual="CORTE", consumo=12.0,
                           aloc_estoque=0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0, origem_api=True)
        prod3 = ProdutoMRP(of="OF1", cod_artigo="4104049", descricao="REGATA", setor_atual="CORTE", consumo=0.25,
                           aloc_estoque=0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0, origem_api=True)
        bloco.produtos = [prod1, prod2, prod3]

        match = casar_com_mrp(self.linha, [bloco], self.cfg)

        # Deve gerar UM ÚNICO MatchInsumo
        self.assertEqual(len(match.insumos), 1)
        self.assertAlmostEqual(match.insumos[0].necessario, 317.25, places=2)

    def test_sem_falso_positivo_cor_divergente_via_api(self):
        # Insumo de material com cor '0' ou '02004' vindo da API para produto com cor '00001'
        bloco = BlocoInsumo(
            cod_insumo="03008234",
            descricao="MALHA TINTA PT",
            un="KG",
            cod_cor="0",  # Código do material no ERP Excia (domínio diferente)
            nome_cor="",
            consumo=1050.0,
            estoque=1050.0,
            compra=0.0,
            tecelagem=0.0,
            pend_tint=0.0,
            tinturaria=0.0,
            saldo=0.0,
            origem_api=True,
            cor_fallback=False, # Não caiu no fallback
        )
        prod = ProdutoMRP(of="OF1", cod_artigo="4104049", descricao="REGATA", setor_atual="CORTE", consumo=1050.0,
                          aloc_estoque=1050.0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0,
                          origem_api=True, cor_fallback=False)
        bloco.produtos = [prod]

        match = casar_com_mrp(self.linha, [bloco], self.cfg)

        self.assertEqual(len(match.insumos), 1)
        self.assertFalse(match.insumos[0].cor_divergente)
        self.assertFalse(any("cor" in a.lower() for a in match.avisos))

    def test_cor_divergente_quando_cor_fallback_true_via_api(self):
        # Quando _resolver_cor_insumo não achou a cor na ficha e usou a primeira
        bloco = BlocoInsumo(
            cod_insumo="03008234",
            descricao="MALHA TINTA PT",
            un="KG",
            cod_cor="02005",
            nome_cor="AZUL",
            consumo=1050.0,
            estoque=1050.0,
            compra=0.0,
            tecelagem=0.0,
            pend_tint=0.0,
            tinturaria=0.0,
            saldo=0.0,
            origem_api=True,
            cor_fallback=True, # Sinalizado fallback
        )
        prod = ProdutoMRP(of="OF1", cod_artigo="4104049", descricao="REGATA", setor_atual="CORTE", consumo=1050.0,
                          aloc_estoque=1050.0, aloc_compra=0, aloc_tecelagem=0, aloc_pend_tint=0, aloc_tinturaria=0, saldo=0,
                          origem_api=True, cor_fallback=True)
        bloco.produtos = [prod]

        match = casar_com_mrp(self.linha, [bloco], self.cfg)

        self.assertEqual(len(match.insumos), 1)
        self.assertTrue(match.insumos[0].cor_divergente)
        self.assertTrue(any("não cadastrada na ficha" in a for a in match.insumos[0].avisos))


if __name__ == "__main__":
    unittest.main()

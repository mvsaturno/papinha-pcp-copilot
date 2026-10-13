"""
engine/cronograma.py — Regra 2: montagem do cronograma draft parametrizável (Sprint 5/6).
Calcula cronograma a partir de lead_times_informados ou sugestões automáticas de cadastro.
Suporta cálculo dinâmico de PCP a partir do MRP e gera JanelaProducao [semana_w, semana_z].
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from engine.models import (
    Cronograma,
    FaseCronograma,
    MatchPedido,
    LinhaPedido,
    PendenciaLeadTime,
    JanelaProducao,
    SugestaoLeadTime,
)
from parsers.comum import (
    semana_aass,
    recuar_dias_uteis_excia,
    avancar_dias_uteis_excia,
    contar_dias_uteis_excia,
    quarta_da_semana,
)
from engine.calendario import obter_paradas_no_intervalo
from api.fluxo_adapter import FluxoAdapter
from api.setor_adapter import normalizar_nome_setor, gerar_sugestao


def montar_cronograma(
    linha: LinhaPedido,
    match: Optional[MatchPedido],
    hoje: date,
    cfg: dict,
    lead_times_informados: Optional[dict[str, tuple[int, int] | list[int] | int | dict]] = None,
    cenario: str = "min",
) -> Cronograma | PendenciaLeadTime:
    """
    Monta o cronograma draft para uma linha de pedido.
    - Se uma etapa foi informada no dict lead_times_informados, seu valor é soberano (usa min no cálculo pontual).
    - Se uma etapa NÃO foi informada, utiliza automaticamente a sugestão (gerar_sugestao) para permitir
      o funcionamento normal da produção, marcando o cronograma como contendo lead times sugeridos não confirmados.
    - Se nem a sugestão estiver disponível (sem_sugestao / dias_min <= 0), devolve PendenciaLeadTime.
    - A etapa PCP é calculada dinamicamente via _calcular_pcp_dias(match, ...), a menos que o analista
      tenha informado explicitamente um valor para "PCP".
    """
    rotas_cfg = cfg.get("rotas", {})

    # 1. Normalizar lead times informados (se houver)
    lts_informados_norm: dict[str, tuple[int, int]] = {}
    if lead_times_informados:
        for k, v in lead_times_informados.items():
            k_norm = normalizar_nome_setor(k)
            if isinstance(v, (tuple, list)) and len(v) >= 2:
                lts_informados_norm[k_norm] = (int(v[0]), int(v[1]))
            elif isinstance(v, dict) and "min" in v and "max" in v:
                lts_informados_norm[k_norm] = (int(v["min"]), int(v["max"]))
            elif isinstance(v, (int, float)):
                lts_informados_norm[k_norm] = (int(v), int(v))

    # 2. Obter partes e códigos de fluxo via API ParteProdutoLista / Fluxo
    fluxo_adapter = FluxoAdapter()
    partes_produto = []
    if getattr(linha, "codigo", None):
        try:
            partes_produto = fluxo_adapter.buscar_todas_partes_produto(linha.codigo)
        except Exception:
            pass

    fluxo_inferido = getattr(linha, "fluxo_id", None)
    if not fluxo_inferido and partes_produto:
        fluxo_inferido = fluxo_adapter.buscar_fluxo_do_produto(linha.codigo)

    fases_dinamicas = None
    if fluxo_inferido:
        try:
            fases_dinamicas = fluxo_adapter.buscar_fases(fluxo_inferido)
        except Exception:
            pass

    if fases_dinamicas:
        rota_nome = f"API ({fluxo_inferido})"
        nomes_fases_rota = list(fases_dinamicas)
    else:
        rota_nome = _detectar_rota(getattr(linha, "descricao", ""), rotas_cfg)
        nomes_fases_rota = list(rotas_cfg.get(rota_nome, rotas_cfg.get("DEFAULT", [])))

    # 3. Resolver duração de cada etapa (com correspondência estritamente EXATA, sem substring)
    todos_setores = list(nomes_fases_rota)
    for p in partes_produto:
        for fn in p.get("fases", []):
            if fn not in todos_setores:
                todos_setores.append(fn)

    lts_efetivos: dict[str, tuple[int, int]] = {}
    setores_faltantes: list[str] = []
    sugestoes_faltantes: dict[str, SugestaoLeadTime] = {}
    etapas_sugeridas: dict[str, SugestaoLeadTime] = {}

    for f_nome in todos_setores:
        f_norm = normalizar_nome_setor(f_nome)
        if f_norm == "PCP":
            # PCP é calculado dinamicamente via MRP a menos que informado
            continue
        if f_norm in lts_informados_norm:
            # Informado explicitamente pelo analista (soberano)
            lts_efetivos[f_norm] = lts_informados_norm[f_norm]
        else:
            # Não informado no dict: buscar sugestão de cadastro/histórico
            sug = gerar_sugestao(getattr(linha, "codigo", "") or "", f_nome)
            if sug.origem == "sem_sugestao" or sug.dias_min <= 0:
                if f_norm not in setores_faltantes:
                    setores_faltantes.append(f_norm)
                    sugestoes_faltantes[f_norm] = sug
            else:
                # Usa sugestão automática para não travar a produção
                lts_efetivos[f_norm] = (sug.dias_min, sug.dias_max)
                etapas_sugeridas[f_norm] = sug

    # Se genuinamente não houver nenhuma sugestão nem valor informado para alguma etapa:
    if setores_faltantes:
        return PendenciaLeadTime(setores_faltantes=setores_faltantes, sugestoes=sugestoes_faltantes)

    # 4. Tratamento e cálculo da duração da etapa PCP (Problema 2)
    if "PCP" in lts_informados_norm:
        # Analista informou explicitamente o valor de PCP no chat -> soberano
        pcp_dias = lts_informados_norm["PCP"][0]
    else:
        # Calcular dinamicamente a partir do MRP e parâmetros de configuração
        fases_dias = cfg.get("fases_dias", {})
        lt_futuro = cfg.get("lead_times_estoque_futuro_dias", {})
        pcp_dias = _calcular_pcp_dias(match, fases_dias, lt_futuro, cfg)

        # Se a rota já possui etapas explícitas de TECELAGEM ou TINTURARIA, PCP é liberação da ordem (2 dias)
        tem_etapas_tecido = any("TECELAGEM" in f.upper() or "TINTURARIA" in f.upper() for f in nomes_fases_rota)
        of_emitida = getattr(linha, "of_emitida", False) or (match and match.of_emitida)
        dt_emissao_of = getattr(linha, "dt_emissao_of", None) or (match and match.dt_emissao_of)
        semana_of = getattr(linha, "semana_of_oficial", None) or (match and match.semana_of_oficial)

        if tem_etapas_tecido and not (of_emitida and dt_emissao_of and semana_of):
            pcp_dias = fases_dias.get("PCP_MIN", 2)

        # Se a OF já foi emitida, calcular PCP exato da ordem entre emissão e semana oficial
        if of_emitida and dt_emissao_of and semana_of:
            fim_of = quarta_da_semana(semana_of)
            dias_outras = sum(
                lts_efetivos[normalizar_nome_setor(fn)][0]
                for fn in nomes_fases_rota
                if "PCP" not in fn.upper() and normalizar_nome_setor(fn) in lts_efetivos
            )
            dias_uteis_totais = contar_dias_uteis_excia(dt_emissao_of, fim_of)
            if dias_uteis_totais > dias_outras:
                pcp_dias = dias_uteis_totais - dias_outras

    lts_efetivos["PCP"] = (pcp_dias, pcp_dias)

    # 5. Montar fases_rota usando lts_efetivos
    idx_cenario = 1 if cenario == "max" else 0
    fases_rota: list[tuple[str, int]] = []
    for f_nome in nomes_fases_rota:
        f_norm = normalizar_nome_setor(f_nome)
        d = lts_efetivos[f_norm][idx_cenario]
        fases_rota.append((f_nome, d))

    # 6. Calcular cronograma principal forward
    def _calcular_fases_forward(lista_fases_dias, dt_inicio):
        fases_calc = []
        cur = dt_inicio
        for nome_f, dias in lista_fases_dias:
            ini = cur
            fim = avancar_dias_uteis_excia(ini, dias)
            paradas = obter_paradas_no_intervalo(ini, fim, setor=nome_f)
            paradas_strs = [f"{p.descricao} {p.inicio.strftime('%d/%m')}–{p.fim.strftime('%d/%m')}" for p in paradas]
            fases_calc.append(FaseCronograma(nome=nome_f, inicio=ini, fim=fim, dias=dias, paradas=paradas_strs))
            cur = fim
        return fases_calc, cur

    fases, data_fim = _calcular_fases_forward(fases_rota, hoje)
    semana_fim = semana_aass(data_fim)

    # 7. Calcular cronogramas de cada parte (se houver múltiplas)
    cronos_partes: dict[str, list[FaseCronograma]] = {}
    partes_info_list = []

    for p in partes_produto:
        p_desc = p.get("descricao") or f"PARTE {p.get('parte')}"
        p_fases_nomes = p.get("fases", [])
        if not p_fases_nomes:
            continue
        p_fases_dias = [(fn, lts_efetivos[normalizar_nome_setor(fn)][idx_cenario]) for fn in p_fases_nomes]
        p_fases_calc, _ = _calcular_fases_forward(p_fases_dias, hoje)
        cronos_partes[p_desc] = p_fases_calc
        partes_info_list.append({
            "parte": p.get("parte"),
            "descricao": p_desc,
            "fluxo": p.get("fluxo"),
            "principal": p.get("principal", False),
        })

    return Cronograma(
        fases=fases,
        rota_detectada=rota_nome,
        pcp_dias=pcp_dias,
        data_fim=data_fim,
        semana_fim_aass=semana_fim,
        cronogramas_partes=cronos_partes,
        partes_info=partes_info_list,
        lead_time_sugerido_nao_confirmado=len(etapas_sugeridas) > 0,
        etapas_sugeridas=etapas_sugeridas,
    )


def montar_janela_producao(
    linha: LinhaPedido,
    match: Optional[MatchPedido],
    hoje: date,
    cfg: dict,
    lead_times_informados: Optional[dict[str, tuple[int, int] | list[int] | int | dict]] = None,
    nova_data_fim: Optional[date] = None,
) -> JanelaProducao | PendenciaLeadTime:
    """
    Calcula a janela de produção [semana_w, semana_z] executando o cronograma duas vezes:
      - Cenário otimista: usando dias_min de cada etapa
      - Cenário pessimista: usando dias_max de cada etapa
    Se faltar qualquer etapa do fluxo sem sugestão, devolve PendenciaLeadTime.
    Caso degenerado (todas as faixas com min == max) -> semana_w == semana_z e cronogramas idênticos.
    """
    lts_min: dict[str, tuple[int, int]] = {}
    lts_max: dict[str, tuple[int, int]] = {}

    if lead_times_informados:
        for k, v in lead_times_informados.items():
            if isinstance(v, (tuple, list)) and len(v) >= 2:
                d_min, d_max = int(v[0]), int(v[1])
            elif isinstance(v, dict) and "min" in v and "max" in v:
                d_min, d_max = int(v["min"]), int(v["max"])
            elif isinstance(v, (int, float)):
                d_min, d_max = int(v), int(v)
            else:
                d_min, d_max = 1, 1
            lts_min[k] = (d_min, d_min)
            lts_max[k] = (d_max, d_max)

    crono_otimista = montar_cronograma(linha, match, hoje, cfg, lts_min if lead_times_informados else None, cenario="min")
    if isinstance(crono_otimista, PendenciaLeadTime):
        return crono_otimista

    crono_pessimista = montar_cronograma(linha, match, hoje, cfg, lts_max if lead_times_informados else None, cenario="max")
    if isinstance(crono_pessimista, PendenciaLeadTime):
        return crono_pessimista

    if nova_data_fim:
        crono_otimista = ajustar_cronograma_backward(crono_otimista, nova_data_fim)
        crono_pessimista = ajustar_cronograma_backward(crono_pessimista, nova_data_fim)

    semana_w = crono_otimista.semana_fim_aass
    semana_z = crono_pessimista.semana_fim_aass

    return JanelaProducao(
        cenario_otimista=crono_otimista,
        cenario_pessimista=crono_pessimista,
        semana_w=semana_w,
        semana_z=semana_z,
    )


def ajustar_cronograma_backward(crono: Cronograma, nova_data_fim: date) -> Cronograma:
    """
    Recalcula as datas do cronograma de trás para a frente para que termine na nova_data_fim.
    Mantém as durações originais das fases (apenas dias úteis), aplicando a todas as partes.
    """
    if not crono.fases:
        return crono

    dias_folga = (nova_data_fim - crono.data_fim).days

    def _calcular_backward(fases_list, dt_fim):
        novas = []
        cur = dt_fim
        for idx, f in enumerate(reversed(fases_list)):
            fim = cur
            inicio = recuar_dias_uteis_excia(fim, f.dias, eh_ultima=(idx == 0))
            paradas = obter_paradas_no_intervalo(inicio, fim, setor=f.nome)
            paradas_strs = [f"{p.descricao} {p.inicio.strftime('%d/%m')}–{p.fim.strftime('%d/%m')}" for p in paradas]
            novas.append(FaseCronograma(
                nome=f.nome,
                inicio=inicio,
                fim=fim,
                dias=f.dias,
                paradas=paradas_strs,
            ))
            cur = inicio
        novas.reverse()
        return novas

    novas_fases = _calcular_backward(crono.fases, nova_data_fim)

    novos_cronos_partes = {}
    for p_nome, p_fases in crono.cronogramas_partes.items():
        novos_cronos_partes[p_nome] = _calcular_backward(p_fases, nova_data_fim)

    crono.fases = novas_fases
    crono.cronogramas_partes = novos_cronos_partes
    crono.data_fim = nova_data_fim
    crono.semana_fim_aass = semana_aass(nova_data_fim)
    crono.folga_dias = dias_folga
    crono.inicio_mais_tarde = novas_fases[0].inicio if novas_fases else None

    return crono


def _detectar_rota(descricao: str, rotas_cfg: dict) -> str:
    """
    Detecta a rota de produção pelo nome do artigo.
    Verifica keywords na ordem de especificidade (mais específico primeiro).
    Fallback: DEFAULT.
    """
    desc_upper = (descricao or "").upper()
    for chave in ["PIJAMA", "CONJUNTO", "VESTIDO", "REGATA", "CAMISETA"]:
        if chave in desc_upper and chave in rotas_cfg:
            return chave
    return "DEFAULT"


def _calcular_pcp_dias(
    match: Optional[MatchPedido],
    fases_dias: dict,
    lt_futuro: dict,
    cfg: dict,
) -> int:
    """
    Calcula a duração dinâmica da fase PCP (espera pelo tecido principal).
    Conforme seção 3.5:
      - OK_ESTOQUE          → pcp_min (2 dias)
      - Tinturaria/PendTint → lead_tinturaria (14 dias)
      - Tecelagem           → lead_tecelagem + lead_tinturaria (21 dias)
      - FALTA               → lead_compra + lead_tecelagem + lead_tinturaria (28 dias)
      - Não localizado      → pcp_padrao (21 dias) + alerta
    """
    pcp_min = fases_dias.get("PCP_MIN", 2)
    pcp_padrao = fases_dias.get("PCP_PADRAO", 21)

    lt_compra = lt_futuro.get("compra", 7)
    lt_tecelagem = lt_futuro.get("tecelagem", 7)
    lt_tinturaria = lt_futuro.get("tinturaria", 14)

    keywords_tecido = cfg.get("tecido_principal_keywords", ["MALHA", "RIBANA"])

    if match is None or not match.insumos:
        return pcp_padrao

    tecido_insumo = None
    for ins in match.insumos:
        desc_upper = (ins.descricao or "").upper()
        for kw in keywords_tecido:
            if kw in desc_upper:
                tecido_insumo = ins
                break
        if tecido_insumo:
            break

    if tecido_insumo is None:
        if getattr(match, "tecido_principal_encontrado", False) and match.insumos:
            tecido_insumo = match.insumos[0]
        else:
            return pcp_padrao

    status = tecido_insumo.status

    if status == "OK_ESTOQUE":
        return pcp_min

    if status == "OK_FUTURO":
        if tecido_insumo.aloc_tinturaria > 0 or tecido_insumo.aloc_pend_tint > 0:
            return lt_tinturaria
        if tecido_insumo.aloc_tecelagem > 0:
            return lt_tecelagem + lt_tinturaria
        if tecido_insumo.aloc_compra > 0:
            return lt_compra + lt_tecelagem + lt_tinturaria
        return pcp_padrao

    if status == "FALTA":
        return lt_compra + lt_tecelagem + lt_tinturaria

    return pcp_padrao

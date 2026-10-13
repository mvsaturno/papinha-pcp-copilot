"""
engine/cronograma.py — Regra 2: montagem do cronograma draft parametrizável (Sprint 5/6).
Calcula cronograma a partir de lead_times_informados e gera JanelaProducao [semana_w, semana_z].
Se faltar qualquer etapa do fluxo real, devolve PendenciaLeadTime (nunca assume valor em silêncio).
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
)
from api.fluxo_adapter import FluxoAdapter
from api.setor_adapter import normalizar_nome_setor, gerar_sugestao


def montar_cronograma(
    linha: LinhaPedido,
    match: Optional[MatchPedido],
    hoje: date,
    cfg: dict,
    lead_times_informados: Optional[dict[str, tuple[int, int] | list[int] | int | dict]] = None,
) -> Cronograma | PendenciaLeadTime:
    """
    Monta o cronograma draft para uma linha de pedido usando estritamente os lead times informados.
    Se faltar a duração de alguma etapa do fluxo real do artigo, retorna PendenciaLeadTime.
    Quando o valor informado for uma faixa (min != max), usa o valor mínimo para este cálculo pontual.
    """
    rotas_cfg = cfg.get("rotas", {})

    # 1. Normalizar lead times informados
    lts_norm: dict[str, tuple[int, int]] = {}
    if lead_times_informados:
        for k, v in lead_times_informados.items():
            k_norm = normalizar_nome_setor(k)
            if isinstance(v, (tuple, list)) and len(v) >= 2:
                lts_norm[k_norm] = (int(v[0]), int(v[1]))
            elif isinstance(v, dict) and "min" in v and "max" in v:
                lts_norm[k_norm] = (int(v["min"]), int(v["max"]))
            elif isinstance(v, (int, float)):
                lts_norm[k_norm] = (int(v), int(v))

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

    # 3. Verificar etapas requeridas e identificar faltantes
    todos_setores = list(nomes_fases_rota)
    for p in partes_produto:
        for fn in p.get("fases", []):
            if fn not in todos_setores:
                todos_setores.append(fn)

    setores_faltantes: list[str] = []
    sugestoes: dict[str, SugestaoLeadTime] = {}

    for f_nome in todos_setores:
        f_norm = normalizar_nome_setor(f_nome)
        if f_norm not in lts_norm:
            # Tentar matching por substring
            matched_key = None
            for k in lts_norm:
                if k == f_norm or k in f_norm or f_norm in k:
                    matched_key = k
                    break
            if matched_key:
                lts_norm[f_norm] = lts_norm[matched_key]
            else:
                if f_norm not in setores_faltantes:
                    setores_faltantes.append(f_norm)
                    sugestoes[f_norm] = gerar_sugestao(getattr(linha, "codigo", "") or "", f_nome)

    # Se faltar qualquer setor, devolve PendenciaLeadTime sem inventar número
    if setores_faltantes:
        return PendenciaLeadTime(setores_faltantes=setores_faltantes, sugestoes=sugestoes)

    # 4. Resolver duração de cada fase da rota principal (usando min se for faixa)
    fases_rota: list[tuple[str, int]] = []
    pcp_dias = 2
    for f_nome in nomes_fases_rota:
        f_norm = normalizar_nome_setor(f_nome)
        d = lts_norm[f_norm][0]
        if "PCP" in f_norm:
            pcp_dias = d
        fases_rota.append((f_nome, d))

    # 5. Calcular cronograma principal forward
    def _calcular_fases_forward(lista_fases_dias, dt_inicio):
        fases_calc = []
        cur = dt_inicio
        for nome_f, dias in lista_fases_dias:
            ini = cur
            fim = avancar_dias_uteis_excia(ini, dias)
            fases_calc.append(FaseCronograma(nome=nome_f, inicio=ini, fim=fim, dias=dias))
            cur = fim
        return fases_calc, cur

    fases, data_fim = _calcular_fases_forward(fases_rota, hoje)
    semana_fim = semana_aass(data_fim)

    # 6. Calcular cronogramas de cada parte (se houver múltiplas)
    cronos_partes: dict[str, list[FaseCronograma]] = {}
    partes_info_list = []

    for p in partes_produto:
        p_desc = p.get("descricao") or f"PARTE {p.get('parte')}"
        p_fases_nomes = p.get("fases", [])
        if not p_fases_nomes:
            continue
        p_fases_dias = [(fn, lts_norm[normalizar_nome_setor(fn)][0]) for fn in p_fases_nomes]
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
    )


def montar_janela_producao(
    linha: LinhaPedido,
    match: Optional[MatchPedido],
    hoje: date,
    cfg: dict,
    lead_times_informados: dict[str, tuple[int, int] | list[int] | int | dict],
    nova_data_fim: Optional[date] = None,
) -> JanelaProducao | PendenciaLeadTime:
    """
    Calcula a janela de produção [semana_w, semana_z] executando o cronograma duas vezes:
      - Cenário otimista: usando dias_min de cada etapa
      - Cenário pessimista: usando dias_max de cada etapa
    Se faltar qualquer etapa do fluxo, devolve PendenciaLeadTime.
    Caso degenerado (todas as faixas com min == max) -> semana_w == semana_z e cronogramas idênticos.
    """
    if not lead_times_informados:
        return montar_cronograma(linha, match, hoje, cfg, {})

    # Monta dicts auxiliares para min e max
    lts_min: dict[str, tuple[int, int]] = {}
    lts_max: dict[str, tuple[int, int]] = {}

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

    crono_otimista = montar_cronograma(linha, match, hoje, cfg, lts_min)
    if isinstance(crono_otimista, PendenciaLeadTime):
        return crono_otimista

    crono_pessimista = montar_cronograma(linha, match, hoje, cfg, lts_max)
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
            novas.append(FaseCronograma(
                nome=f.nome,
                inicio=inicio,
                fim=fim,
                dias=f.dias
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

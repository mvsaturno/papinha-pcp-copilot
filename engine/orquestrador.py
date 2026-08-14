"""
engine/orquestrador.py — Orquestra a análise de um pedido via número.
Sprint 4: busca todos os dados via API (pedido, OFs, MRP, capacidade)
e delega a análise completa ao engine/analise.py (fonte única de veredito).
"""

from datetime import date
from typing import Optional

from engine.models import ResultadoAnalise, Pedido
from api.pedido_adapter import PedidoAdapter
from api.capacidade_adapter import CapacidadeAdapter
from api.mrp_adapter import MrpAdapter
from api.excia_client import ExciaAPIClient
from engine.analise import analisar


def analisar_pedido_por_numero(numero_pedido: str, cfg: dict) -> ResultadoAnalise:
    """
    Orquestra a análise de um pedido consultando a API da Excia.
    Fluxo:
      1. Buscar pedido via BuscarPedido
      2. Buscar OFs vinculadas via OPLista?pedido=NUMERO (campo 'pedido' confirmado na API)
      3. Buscar capacidade via OPLista (todas OPs pendentes)
      4. Explodir MRP (ficha técnica + estoque + ordens futuras)
      5. Delegar análise completa ao engine.analise.analisar()
    """
    hoje = date.today()
    resultado = ResultadoAnalise(
        timestamp=hoje.isoformat(),
        data_analise=hoje,
    )

    # ── 1. Buscar pedido ──────────────────────────────────────────────────
    pedido_adapter = PedidoAdapter()
    pedido = pedido_adapter.buscar_pedido(numero_pedido)

    if not pedido:
        resultado.erros_entrada.append({
            "campo": "numero_pedido",
            "mensagem": (
                f"Pedido {numero_pedido} não encontrado no Excia. "
                "Confira o número e tente novamente."
            )
        })
        return resultado

    if not pedido.linhas:
        resultado.erros_entrada.append({
            "campo": "numero_pedido",
            "mensagem": (
                f"Pedido {numero_pedido} foi encontrado mas não tem linhas de produto. "
                "Verifique se o pedido está ativo no Excia."
            )
        })
        return resultado

    # ── 2. Buscar capacidade (já indexa todas as OFs do sistema) ──────────
    cap_adapter = CapacidadeAdapter()
    try:
        cap = cap_adapter.buscar_capacidade(cfg=cfg)
    except Exception as e:
        resultado.erros_entrada.append({
            "campo": "capacidade",
            "mensagem": f"Falha ao buscar capacidade na API: {str(e)}"
        })
        return resultado

    # ── 3. Enriquecer linhas com OFs e fluxo oficial ─────────────────────
    _enriquecer_linhas_com_ofs(pedido, numero_pedido, cap_adapter, cfg)

    # ── 4. Explodir MRP ───────────────────────────────────────────────────
    try:
        mrp_adapter = MrpAdapter()
        mrp = mrp_adapter.explodir_necessidades(pedido.linhas)
    except Exception as e:
        resultado.avisos_leitura.append(
            f"⚠️ Falha ao buscar explosão de materiais na API: {str(e)}. "
            "A análise prossegue sem dados de insumos."
        )
        mrp = []

    # ── 5. Delegar análise ao engine (única fonte de verdade) ─────────────
    try:
        resultado = analisar([pedido], mrp, cap, hoje, cfg, resultado)
    except Exception as e:
        resultado.avisos_leitura.append(f"Erro inesperado na análise: {str(e)}")

    return resultado


def _enriquecer_linhas_com_ofs(
    pedido: Pedido, numero_pedido: str, cap_adapter: CapacidadeAdapter, cfg: dict
) -> None:
    """
    Associa as OFs abertas para este pedido e descobre o fluxo do produto via API Excia.
    Quando uma OF existe:
      - Marca linha.of_emitida = True
      - Preenche linha.numero_of, linha.semana_of_oficial, linha.dt_emissao_of e linha.qtde_of_oficial
      - Descobre o código do fluxo oficial da peça via ParteProdutoLista.
    """
    from parsers.comum import parse_data_br
    from api.fluxo_adapter import FluxoAdapter

    fluxo_adapter = FluxoAdapter()
    
    # 1. Descobrir fluxo do produto para cada linha via ParteProdutoLista
    for linha in pedido.linhas:
        if linha.codigo and not getattr(linha, "fluxo_id", None):
            try:
                fl = fluxo_adapter.buscar_fluxo_do_produto(linha.codigo)
                if fl:
                    linha.fluxo_id = fl
            except Exception:
                pass

    # 2. Obter OFs ativas do pedido direto do índice em memória
    ops_do_pedido = cap_adapter.buscar_ofs_do_pedido(numero_pedido)
    
    # Fallback se não indexou ainda
    if not ops_do_pedido:
        try:
            client = ExciaAPIClient()
            resp = client.get("OPLista", params={"emissao": "01/01/2025", "situacao": "P"})
            if resp and isinstance(resp, list):
                ops_do_pedido = [op for op in resp if str(op.get("pedido", "")).strip() == str(numero_pedido).strip()]
        except Exception:
            pass

    if ops_do_pedido:
        for linha in pedido.linhas:
            op_match = None
            for op in ops_do_pedido:
                if str(op.get("codigo", "")).strip() == str(linha.codigo).strip():
                    op_match = op
                    break
            if not op_match and ops_do_pedido:
                op_match = ops_do_pedido[0]

            if op_match:
                linha.of_emitida = True
                linha.numero_of = str(op_match.get("numero", ""))
                
                p_str = str(op_match.get("periodo", "")).strip()
                if p_str and p_str.isdigit():
                    linha.semana_of_oficial = int(p_str)
                
                dt_ini_str = str(op_match.get("dt_inicio", "")).strip()
                if dt_ini_str:
                    try:
                        linha.dt_emissao_of = parse_data_br(dt_ini_str)
                    except Exception:
                        pass
                
                q_of = sum(float(it.get("qtde") or 0.0) for it in op_match.get("itens", []))
                if q_of > 0:
                    linha.qtde_of_oficial = int(q_of)

        pedido.avisos_parsing.append(
            f"🏷️ Pedido {numero_pedido} já possui OF emitida no Excia: OF {ops_do_pedido[0].get('numero')} "
            f"(Semana Oficial: {ops_do_pedido[0].get('periodo')})."
        )
    else:
        pedido.avisos_parsing.append(
            f"ℹ️ Pedido {numero_pedido} ainda não possui OF emitida (Simulação Pré-OF)."
        )

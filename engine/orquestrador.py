from datetime import date
from engine.models import (
    CardPedido, ResultadoAnalise, MatchPedido, MatchInsumo, Cronograma
)
from api.pedido_adapter import PedidoAdapter
from api.capacidade_adapter import CapacidadeAdapter
from engine.analise import (
    montar_cronograma, avaliar_insumos, verificar_capacidade_pedido
)
from parsers.comum import arredondar, formatar_data_br, semana_aass
import copy

def analisar_pedido_por_numero(numero_pedido: str, cfg: dict) -> ResultadoAnalise:
    """
    Orquestra a análise de um pedido consultando a API da Excia.
    Substitui a dependência de PDFs pelo consumo de endpoints.
    """
    hoje = date.today()
    resultado = ResultadoAnalise(
        timestamp=hoje.isoformat(),
        data_analise=hoje,
    )

    # 1. Buscar pedido via API
    pedido_adapter = PedidoAdapter()
    pedido = pedido_adapter.buscar_pedido(numero_pedido)
    
    if not pedido:
        resultado.erros_entrada.append({
            "campo": "numero_pedido",
            "mensagem": f"Pedido {numero_pedido} não encontrado no Excia. Confira o número e tente novamente."
        })
        return resultado

    # 2. Buscar capacidade (Opção B - via API)
    cap_adapter = CapacidadeAdapter()
    try:
        cap_parsed = cap_adapter.buscar_capacidade(hoje)
    except Exception as e:
        resultado.erros_entrada.append({
            "campo": "capacidade",
            "mensagem": f"Falha ao buscar capacidade na API: {str(e)}"
        })
        return resultado

    # Iterar sobre as linhas do pedido já agrupadas pelo adapter
    for linha in pedido.linhas:
        avisos = []
        
        # 3. Ficha Técnica (Placeholder)
        ficha = None # api.produto_adapter.buscar_ficha_tecnica(linha.codigo)
        if ficha is None:
            avisos.append(
                f"Artigo {linha.codigo} sem ficha técnica cadastrada na API — "
                f"análise de insumos não pôde ser feita."
            )
            
        # 4. Rota (Placeholder)
        rota = None # api.rota_adapter.buscar_rota(linha.codigo)
        rota_nome = "DEFAULT"
        if rota is None:
            avisos.append(
                f"Rota de produção não encontrada via API para o artigo {linha.codigo} — "
                f"usando rota padrão de fallback."
            )
            
        # 5. Estoque (Placeholder)
        estoque = {} # api.estoque_adapter.buscar_estoque(...)
        
        # 6. OP (Placeholder)
        op = None # api.op_adapter.buscar_op_por_pedido(...)
        
        # 7. Insumos (Placeholder - MRP removido no Sprint 4 Option B)
        # Como não temos ficha técnica nem estoque real por enquanto, o MatchPedido fica vazio
        match = MatchPedido(
            cod_artigo=linha.codigo,
            of=op.numero if op else "",
            confianca="BAIXA",
            insumos=[],
            avisos=avisos,
            tecido_principal_encontrado=False
        )

        # 8-10. Reaproveitar engine existente
        qtd_of = arredondar(
            linha.qtde_total * (1 + cfg["geral"]["buffer_producao_pct"] / 100),
            cfg["geral"]["arredondamento"]
        )
        
        cronograma = montar_cronograma(linha.descricao, rota_nome, hoje, cfg)
        # O prazo do item vem da API (dt_entrega_item)
        dt_entrega = linha.dt_entrega_item or pedido.entrega
        semana_entrega = semana_aass(dt_entrega)
        
        # Subtrair dias de PCP da entrega para achar a semana alvo de finalização
        from datetime import timedelta
        alvo_date = dt_entrega - timedelta(days=cronograma.pcp_dias)
        semana_alvo = semana_aass(alvo_date)
        
        # Como match.insumos está vazio, não haverá atraso por insumo, mas chamamos para manter fluxo
        insumos_avaliados, data_liberacao_insumo = avaliar_insumos(match.insumos, hoje)
        
        analise_cap = verificar_capacidade_pedido(
            qtd_of=qtd_of,
            semana_alvo=semana_alvo,
            cap=cap_parsed,
            cfg=cfg
        )
        
        # Determinar Veredito
        if len(analise_cap.avisos) > 0 and not analise_cap.cabe_no_alvo:
            veredito = "VERMELHO"
            motivos = analise_cap.avisos.copy()
            sugestao = f"Sugerido transferir para semana {analise_cap.semana_sugerida}." if analise_cap.semana_sugerida else "Semana sugerida não encontrada no horizonte."
        else:
            veredito = "VERDE"
            motivos = ["Capacidade OK para a semana alvo."]
            sugestao = "Manter planejamento."
            
        dados_brutos = {
            "pedido_numero": pedido.numero,
            "ped_cliente": pedido.ped_cliente,
            "artigo": linha.codigo,
            "descricao": linha.descricao,
            "grade": linha.grade,
            "qtde_total": linha.qtde_total,
            "qtd_of": qtd_of,
            "emissao": formatar_data_br(pedido.emissao),
            "entrega": formatar_data_br(pedido.entrega),
            "semana_entrega_aass": semana_entrega,
            "semana_alvo_aass": semana_alvo,
        }
        
        card = CardPedido(
            numero_pedido=pedido.numero,
            artigo=linha.codigo,
            descricao=linha.descricao,
            cod_cor=linha.cor,
            nome_cor=linha.desc_cor,
            qtde_pedido=linha.qtde_total,
            qtd_of=qtd_of,
            entrega_cliente=dt_entrega,
            semana_alvo=semana_alvo,
            veredito=veredito,
            motivos=motivos,
            match=match,
            insumos=insumos_avaliados,
            cronograma=cronograma,
            capacidade=analise_cap,
            sugestao=sugestao,
            sugestao_semana=analise_cap.semana_sugerida,
            dados_brutos=dados_brutos
        )
        
        resultado.pedidos.append(card)

    return resultado

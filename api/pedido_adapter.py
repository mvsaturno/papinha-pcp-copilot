from .excia_client import ExciaAPIClient
from engine.models import Pedido, LinhaPedido
from datetime import datetime

class PedidoAdapter:
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()

    def buscar_pedido(self, numero_pedido: str) -> Pedido | None:
        """
        Busca um pedido na API e retorna um objeto Pedido (ou None se não encontrado).
        """
        response = self.client.get("BuscarPedido", params={"numero": numero_pedido})
        
        if not response or not isinstance(response, list) or len(response) == 0:
            return None
            
        dados = response[0]
        
        # O formato da data retornado pode ser 'DD/MM/YYYY'. Convertendo para date.
        try:
            emissao = datetime.strptime(dados.get("dt_emissao", ""), "%d/%m/%Y").date()
        except ValueError:
            emissao = datetime.today().date()
            
        try:
            entrega = datetime.strptime(dados.get("entrega", ""), "%d/%m/%Y").date()
        except ValueError:
            entrega = datetime.today().date()

        pedido = Pedido(
            numero=dados.get("numero", numero_pedido),
            ped_cliente=dados.get("ped_cli", ""),
            emissao=emissao,
            entrega=entrega,
            cliente=dados.get("nome", ""),
            colecao=dados.get("desc_colecao", ""),
            linhas=[]
        )
        
        # A API retorna os itens na chave 'itens'
        itens_brutos = dados.get("itens", [])
        
        # Agrupar itens por (codigo, cor)
        agrupados = {}
        for item in itens_brutos:
            codigo = item.get("codigo", "")
            cor = item.get("cor", "")
            key = (codigo, cor)
            
            if key not in agrupados:
                agrupados[key] = {
                    "codigo": codigo,
                    "cor": cor,
                    "desc_cor": item.get("desc_cor", ""),
                    "descricao": item.get("descricao", ""),
                    "grade": {},
                    "qtde_total": 0.0,
                    "dt_entrega_item": None
                }
                
                try:
                    dt_ent = datetime.strptime(item.get("dt_entrega", ""), "%d/%m/%Y").date()
                    agrupados[key]["dt_entrega_item"] = dt_ent
                except ValueError:
                    agrupados[key]["dt_entrega_item"] = entrega

            tam = str(item.get("tam", ""))
            qtde = float(item.get("qtde", 0.0))
            
            if tam in agrupados[key]["grade"]:
                agrupados[key]["grade"][tam] += qtde
            else:
                agrupados[key]["grade"][tam] = qtde
                
            agrupados[key]["qtde_total"] += qtde

        # Converter para objetos LinhaPedido
        for props in agrupados.values():
            linha = LinhaPedido(
                codigo=props["codigo"],
                cor=props["cor"],
                desc_cor=props["desc_cor"],
                descricao=props["descricao"],
                grade=props["grade"],
                qtde_total=props["qtde_total"],
                dt_entrega_item=props["dt_entrega_item"]
            )
            pedido.linhas.append(linha)

        return pedido

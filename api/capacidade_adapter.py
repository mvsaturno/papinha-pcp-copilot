from .excia_client import ExciaAPIClient
from engine.models import CapacidadeSemanal
from datetime import datetime, date

class CapacidadeAdapter:
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()

    def buscar_capacidade(self, data_emissao: date = None) -> CapacidadeSemanal:
        """
        Busca a capacidade produtiva a partir de OPs pendentes (impof=0)
        e retorna um objeto CapacidadeSemanal agrupado por período (AASS).
        """
        if not data_emissao:
            data_emissao = date(datetime.today().year, 1, 1) # Fallback para 1 de jan do ano atual
            
        emissao_str = data_emissao.strftime("%d/%m/%Y")
        
        periodos_dict = {}
        pagina = 1
        max_paginas = 20 # Limite de segurança
        
        while pagina <= max_paginas:
            params = {
                "emissao": emissao_str,
                "impof": 0,
                "pagina": pagina
            }
            
            response = self.client.get("OPLista", params=params)
            
            if not response or not isinstance(response, list) or len(response) == 0:
                break # Sem mais páginas ou erro
                
            for op in response:
                periodo_str = op.get("periodo", "")
                if not periodo_str.isdigit():
                    continue
                    
                periodo_int = int(periodo_str)
                itens = op.get("itens", [])
                
                # A requisição de teste mostrou qtde_b com o valor e qtde com 0. 
                # Vamos somar os dois para garantir que pegamos o valor da OP.
                soma_op = 0
                for item in itens:
                    qtde = float(item.get("qtde", 0.0))
                    qtde_b = float(item.get("qtde_b", 0.0))
                    soma_op += max(qtde, qtde_b)
                
                if periodo_int in periodos_dict:
                    periodos_dict[periodo_int] += int(soma_op)
                else:
                    periodos_dict[periodo_int] = int(soma_op)
            
            if len(response) < 300: # 300 registros por página de acordo com a documentação
                break
                
            pagina += 1

        return CapacidadeSemanal(
            periodos=periodos_dict,
            data_relatorio=datetime.today().date()
        )

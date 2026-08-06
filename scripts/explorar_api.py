import os
import sys
import json

# Adiciona o diretório raiz ao path para importar 'api'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.excia_client import ExciaAPIClient

def save_json(name, data):
    out_dir = os.path.join(os.path.dirname(__file__), 'output_exploratorio')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{name}.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {name}.json")

def main():
    client = ExciaAPIClient()
    
    pedidos = ['102559', '102562', '102578', '102580', '102622', '94736']
    ops = ['263005', '263701', '263702', '263920', '263921', '263922']
    artigos = ['4104040', '4104046', '1104017', '1104018', '1104019', '1004383']
    
    # 1. Buscar Pedido
    print("--- Testando /BuscarPedido ou /PedidoLista ---")
    for ped in pedidos:
        # Vamos tentar BuscarPedido primeiro
        try:
            res = client.get('BuscarPedido', params={'pedido': ped})
            if res: save_json(f"BuscarPedido_{ped}", res)
        except Exception as e:
            print(f"Erro BuscarPedido {ped}: {e}")
        
        # Vamos tentar PedidoLista também
        try:
            res = client.get('PedidoLista', params={'pedido': ped})
            if res: save_json(f"PedidoLista_{ped}", res)
        except Exception as e:
            print(f"Erro PedidoLista {ped}: {e}")

    # 2. OPLista
    print("--- Testando /OPLista ---")
    for op in ops:
        try:
            res = client.get('OPLista', params={'op': op})
            if res: save_json(f"OPLista_{op}", res)
        except Exception as e:
            print(f"Erro OPLista {op}: {e}")

    # 3. BuscarFichaTecnicaProduto
    print("--- Testando /BuscarFichaTecnicaProduto ---")
    for art in artigos:
        try:
            res = client.get('BuscarFichaTecnicaProduto', params={'produto': art})
            if res: save_json(f"BuscarFichaTecnicaProduto_{art}", res)
        except Exception as e:
            print(f"Erro BuscarFichaTecnicaProduto {art}: {e}")

    # 4. ParteProduto e Fluxo
    print("--- Testando /ParteProduto e /Fluxo ---")
    for art in artigos:
        try:
            res_parte = client.get('ParteProduto', params={'produto': art})
            if res_parte: 
                save_json(f"ParteProduto_{art}", res_parte)
                # se tiver fluxo, vamos buscar o fluxo
                if isinstance(res_parte, list) and len(res_parte) > 0 and 'fluxo' in res_parte[0]:
                    fluxo = res_parte[0]['fluxo']
                    res_fluxo = client.get(f'Fluxo/{fluxo}')
                    if res_fluxo:
                        save_json(f"Fluxo_{fluxo}_(art_{art})", res_fluxo)
        except Exception as e:
            print(f"Erro ParteProduto/Fluxo {art}: {e}")

    # 5. Estoque?tipo=M (Ribana etc)
    print("--- Testando /Estoque ---")
    insumos = ['03044079'] # Exemplo de Ribana
    for ins in insumos:
        try:
            res = client.get('Estoque', params={'tipo': 'M', 'material': ins})
            if res: save_json(f"Estoque_M_{ins}", res)
        except Exception as e:
            print(f"Erro Estoque {ins}: {e}")

if __name__ == "__main__":
    main()

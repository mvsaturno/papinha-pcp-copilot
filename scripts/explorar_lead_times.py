"""
scripts/explorar_lead_times.py — Rodar NA VM (onde a API do Excia é alcançável).

Objetivo: descobrir onde o Excia expõe, via API, (a) os lead times por setor e
(b) o cronograma planejado da OF (datas por setor), para um pedido de referência.

Uso:
    cd ~/papinha-pcp-copilot && python scripts/explorar_lead_times.py 107487

Salva o JSON bruto de cada chamada em scripts/output_exploratorio/lead_times/ e
imprime um resumo: campos numéricos encontrados por setor e, se houver datas por
setor no fluxo do pedido/OF, os dias úteis calculados entre elas.
Somente leitura. Nenhuma chamada POST/PATCH/DELETE.
"""

import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.excia_client import ExciaAPIClient  # noqa: E402
from parsers.comum import contar_dias_uteis_excia  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "output_exploratorio", "lead_times")
os.makedirs(OUT, exist_ok=True)


def salvar(nome, dados):
    caminho = os.path.join(OUT, f"{nome}.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(f"  salvo: {os.path.relpath(caminho)}")


def get(client, endpoint, params=None):
    try:
        r = client.get(endpoint, params=params)
        return r if r is not None else []
    except Exception as e:  # noqa: BLE001
        print(f"  ERRO {endpoint} {params}: {e}")
        return []


def chaves_numericas(obj, prefixo=""):
    """Lista campos numéricos (candidatos a 'dias'/'prazo') em qualquer nível."""
    achados = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                achados.append((f"{prefixo}{k}", v))
            elif isinstance(v, str) and v.strip().isdigit() and k.lower() not in ("codigo", "setor", "ordem", "parte", "fluxo", "numero", "periodo"):
                achados.append((f"{prefixo}{k}", v))
            else:
                achados += chaves_numericas(v, f"{prefixo}{k}.")
    elif isinstance(obj, list):
        for i, it in enumerate(obj[:3]):
            achados += chaves_numericas(it, f"{prefixo}[{i}].")
    return achados


def data_br(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:  # noqa: BLE001
        return None


def main():
    numero_pedido = sys.argv[1] if len(sys.argv) > 1 else "107487"
    client = ExciaAPIClient()

    print(f"\n[1] SetorLista + Setor/:codigo — procurar campos além de codigo/descricao/tipo")
    setores = get(client, "SetorLista")
    salvar("SetorLista", setores)
    campos_setor = set()
    for s in setores if isinstance(setores, list) else []:
        cod = str(s.get("codigo", "")).strip()
        det = get(client, f"Setor/{cod}") if cod else []
        if det:
            salvar(f"Setor_{cod}", det)
            for item in det:
                campos_setor |= set(item.keys())
    print(f"  campos vistos em Setor/:codigo: {sorted(campos_setor)}")
    extras = campos_setor - {"codigo", "descricao", "tipo"}
    print(f"  campos NÃO documentados: {sorted(extras) or 'nenhum'}")

    print(f"\n[2] Pedido {numero_pedido} → produtos → ParteProdutoLista → Fluxo/:codigo")
    ped = get(client, "BuscarPedido", params={"numero": numero_pedido})
    salvar(f"BuscarPedido_{numero_pedido}", ped)
    codigos = sorted({it.get("codigo") for p in (ped or []) for it in p.get("itens", []) if it.get("codigo")})
    print(f"  produtos do pedido: {codigos}")
    fluxos = set()
    for cod in codigos:
        partes = get(client, "ParteProdutoLista", params={"codigo": cod})
        salvar(f"ParteProdutoLista_{cod}", partes)
        for p in partes if isinstance(partes, list) else []:
            if p.get("fluxo"):
                fluxos.add(str(p["fluxo"]))
            nums = chaves_numericas(p)
            if nums:
                print(f"  ParteProduto {cod} parte {p.get('parte')}: campos numéricos {nums}")
    for fl in sorted(fluxos):
        fx = get(client, f"Fluxo/{fl}")
        salvar(f"Fluxo_{fl}", fx)
        for f in fx if isinstance(fx, list) else []:
            for st in f.get("setores", []):
                extras_st = set(st.keys()) - {"setor", "descricao", "ordem"}
                print(f"  Fluxo {fl} setor {st.get('setor')} {st.get('descricao')}: "
                      f"extras={sorted(extras_st) or 'nenhum'} numéricos={chaves_numericas(st)}")

    print(f"\n[3] Pedido/Fluxo?numero={numero_pedido} — datas planejadas por setor?")
    pf = get(client, "Pedido/Fluxo", params={"numero": numero_pedido})
    salvar(f"PedidoFluxo_{numero_pedido}", pf)
    if isinstance(pf, list) and pf:
        print(f"  {len(pf)} linhas. Campos: {sorted(pf[0].keys())}")
        linhas = sorted(pf, key=lambda x: (x.get("codigo", ""), data_br(x.get("dt_inicio", "")) or date.min))
        for l in linhas:
            di, dp, df = data_br(l.get("dt_inicio", "")), data_br(l.get("dt_prev", "")), data_br(l.get("dt_fim", ""))
            dur_prev = contar_dias_uteis_excia(di, dp) if di and dp else None
            print(f"  {l.get('codigo')} | setor {l.get('setor')} {l.get('desc_setor')} | "
                  f"ini {l.get('dt_inicio')} prev {l.get('dt_prev')} fim {l.get('dt_fim')} | "
                  f"dias úteis ini→prev = {dur_prev} | sit {l.get('situacao')}")
    else:
        print("  vazio — este endpoint não traz fluxo para o pedido.")

    print(f"\n[4] OPLista — OFs do pedido {numero_pedido} e BuscarMovimentacaoOP por setor")
    ops = []
    pagina = 1
    while pagina <= 20:
        lote = get(client, "OPLista", params={"emissao": "01/01/2025", "situacao": "P", "pagina": pagina})
        if not lote:
            break
        ops += [op for op in lote if str(op.get("pedido", "")).strip() == numero_pedido]
        if len(lote) < 300:
            break
        pagina += 1
    salvar(f"OPLista_pedido_{numero_pedido}", ops)
    print(f"  OFs encontradas: {[op.get('numero') for op in ops]}")
    for op in ops:
        extras_op = set(op.keys()) - {"numero", "parte", "codigo", "dt_inicio", "periodo", "partes", "pedido", "tipo",
                                      "impof", "codcli", "descricao", "maquina", "sequencial", "deposito", "itens"}
        print(f"  OF {op.get('numero')} parte {op.get('parte')} periodo {op.get('periodo')} dt_inicio {op.get('dt_inicio')} "
              f"| campos extras: {sorted(extras_op) or 'nenhum'}")
        for fl in sorted(fluxos):
            fx = get(client, f"Fluxo/{fl}")
            for f in fx if isinstance(fx, list) else []:
                for st in f.get("setores", []):
                    mov = get(client, "BuscarMovimentacaoOP",
                              params={"numero": op.get("numero"), "parte": op.get("parte") or "01", "setor": st.get("setor")})
                    if mov:
                        salvar(f"MovOP_{op.get('numero')}_{st.get('setor')}", mov)
                        print(f"    mov setor {st.get('setor')} {st.get('descricao')}: campos {sorted(mov[0].keys())} "
                              f"numéricos {chaves_numericas(mov[0])[:6]}")

    print("\nConcluído. Envie a pasta scripts/output_exploratorio/lead_times/ para análise.")


if __name__ == "__main__":
    main()

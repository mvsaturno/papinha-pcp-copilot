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


class NaoAutorizado(Exception):
    """Token sem permissão para o endpoint (HTTP 401/403)."""


def get(client, endpoint, params=None):
    """GET sem retry (exploração): 401/403 viram NaoAutorizado; outros erros viram []."""
    try:
        r = client.get(endpoint, params=params, max_retries=1)
        return r if r is not None else []
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "401" in msg or "403" in msg:
            raise NaoAutorizado(f"{endpoint}: token sem permissão ({msg[:40]})") from e
        print(f"  ERRO {endpoint} {params}: {msg[:160]}")
        return []


def secao(titulo, fn):
    """Roda uma seção isolando falhas: 401 ou exceção não derrubam o resto."""
    print(f"\n{titulo}")
    try:
        fn()
    except NaoAutorizado as e:
        print(f"  PULANDO: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"  FALHA inesperada na seção: {e!r}")


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
    estado = {"codigos": [], "fluxos": set(), "ops": []}

    def s1():
        setores = get(client, "SetorLista")
        salvar("SetorLista", setores)
        print(f"  {len(setores)} setores. campos na lista: {sorted(setores[0].keys()) if setores else '-'}")
        campos_setor = set()
        for s in (setores if isinstance(setores, list) else [])[:3]:  # amostra: 3 setores bastam
            cod = str(s.get("codigo", "")).strip()
            det = get(client, f"Setor/{cod}") if cod else []
            if det:
                salvar(f"Setor_{cod}", det)
                for item in det:
                    campos_setor |= set(item.keys())
        extras = campos_setor - {"codigo", "descricao", "tipo"}
        print(f"  campos em Setor/:codigo: {sorted(campos_setor) or '-'} | NÃO documentados: {sorted(extras) or 'nenhum'}")

    def s2():
        ped = get(client, "BuscarPedido", params={"numero": numero_pedido})
        salvar(f"BuscarPedido_{numero_pedido}", ped)
        codigos = sorted({it.get("codigo") for p in (ped or []) for it in p.get("itens", []) if it.get("codigo")})
        estado["codigos"] = codigos
        print(f"  produtos do pedido: {codigos}")
        for cod in codigos:
            partes = get(client, "ParteProdutoLista", params={"codigo": cod})
            salvar(f"ParteProdutoLista_{cod}", partes)
            for p in partes if isinstance(partes, list) else []:
                if p.get("fluxo"):
                    estado["fluxos"].add(str(p["fluxo"]))
                nums = chaves_numericas(p)
                if nums:
                    print(f"  ParteProduto {cod} parte {p.get('parte')}: campos numéricos {nums}")
        for fl in sorted(estado["fluxos"]):
            fx = get(client, f"Fluxo/{fl}")
            salvar(f"Fluxo_{fl}", fx)
            for f in fx if isinstance(fx, list) else []:
                extras_f = set(f.keys()) - {"codigo", "descricao", "baixalivre", "setores"}
                print(f"  Fluxo {fl} '{f.get('descricao')}' campos extras no fluxo: {sorted(extras_f) or 'nenhum'}")
                for st in f.get("setores", []):
                    extras_st = set(st.keys()) - {"setor", "descricao", "ordem"}
                    print(f"    setor {st.get('setor')} {st.get('descricao')}: "
                          f"extras={sorted(extras_st) or 'nenhum'} numéricos={chaves_numericas(st)}")

    def s3():
        pf = get(client, "Pedido/Fluxo", params={"numero": numero_pedido})
        salvar(f"PedidoFluxo_{numero_pedido}", pf)
        if isinstance(pf, list) and pf and not pf[0].get("method-error-400"):
            print(f"  {len(pf)} linhas. Campos: {sorted(pf[0].keys())}")
            linhas = sorted(pf, key=lambda x: (x.get("codigo", ""), data_br(x.get("dt_inicio", "")) or date.min))
            for l in linhas:
                di, dp = data_br(l.get("dt_inicio", "")), data_br(l.get("dt_prev", ""))
                dur_prev = contar_dias_uteis_excia(di, dp) if di and dp else None
                print(f"  {l.get('codigo')} | setor {l.get('setor')} {l.get('desc_setor')} | "
                      f"ini {l.get('dt_inicio')} prev {l.get('dt_prev')} fim {l.get('dt_fim')} | "
                      f"dias úteis ini→prev = {dur_prev} | sit {l.get('situacao')}")
        else:
            print(f"  vazio ou erro — este endpoint não traz fluxo para o pedido. Resposta: {str(pf)[:200]}")

    def s4():
        ops, pagina = [], 1
        while pagina <= 20:
            lote = get(client, "OPLista", params={"emissao": "01/01/2025", "situacao": "P", "pagina": pagina})
            if not lote:
                break
            ops += [op for op in lote if str(op.get("pedido", "")).strip() == numero_pedido]
            if len(lote) < 300:
                break
            pagina += 1
        estado["ops"] = ops
        salvar(f"OPLista_pedido_{numero_pedido}", ops)
        print(f"  OFs encontradas: {[op.get('numero') for op in ops]}")
        documentados = {"numero", "parte", "codigo", "dt_inicio", "periodo", "partes", "pedido", "tipo",
                        "impof", "codcli", "descricao", "maquina", "sequencial", "deposito", "itens"}
        for op in ops:
            print(f"  OF {op.get('numero')} parte {op.get('parte')} periodo {op.get('periodo')} "
                  f"dt_inicio {op.get('dt_inicio')} | campos extras: {sorted(set(op.keys()) - documentados) or 'nenhum'}")

    def s5():
        if not estado["ops"]:
            print("  sem OFs; nada a consultar.")
            return
        setores_fluxo = []
        for fl in sorted(estado["fluxos"]):
            for f in get(client, f"Fluxo/{fl}") or []:
                setores_fluxo += [(st.get("setor"), st.get("descricao")) for st in f.get("setores", [])]
        op = estado["ops"][0]
        for cod_st, desc_st in setores_fluxo:
            mov = get(client, "BuscarMovimentacaoOP",
                      params={"numero": op.get("numero"), "parte": op.get("parte") or "01", "setor": cod_st})
            if mov and not mov[0].get("method-error-400"):
                salvar(f"MovOP_{op.get('numero')}_{cod_st}", mov)
                print(f"  setor {cod_st} {desc_st}: campos {sorted(mov[0].keys())} numéricos {chaves_numericas(mov[0])[:6]}")
            else:
                print(f"  setor {cod_st} {desc_st}: sem movimentação")

    secao("[1] SetorLista + amostra de Setor/:codigo", s1)
    secao(f"[2] Pedido {numero_pedido} → ParteProdutoLista → Fluxo/:codigo", s2)
    secao(f"[3] Pedido/Fluxo?numero={numero_pedido} — datas planejadas por setor?", s3)
    secao(f"[4] OPLista — OFs do pedido {numero_pedido}", s4)
    secao("[5] BuscarMovimentacaoOP por setor da primeira OF", s5)
    print("\nConcluído. Envie a pasta scripts/output_exploratorio/lead_times/ para análise.")


if __name__ == "__main__":
    main()

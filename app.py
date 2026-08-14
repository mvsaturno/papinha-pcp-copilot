"""
app.py — FastAPI: serve UI estática + endpoints de análise.
Um único processo local: python app.py → abre http://localhost:8000
"""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from datetime import date
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Imports internos ────────────────────────────────────────────────────────
from parsers.validacao import identificar_tipo, Identificacao
from parsers.pedido_parser import parse_pedido
from parsers.mrp_parser import parse_mrp
from parsers.capacidade_parser import parse_capacidade
from engine.models import ResultadoAnalise, TipoPDF
from engine.analise import analisar
from engine.orquestrador import analisar_pedido_por_numero

# ── Configuração ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "regras.yaml"

with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Copiloto PCP — Papinha Baby", version="1.0.0-mvp")

import threading
from api.capacidade_adapter import CapacidadeAdapter

@app.on_event("startup")
async def startup_event():
    """Pré-aquece o cache de capacidade em background para garantir resposta instantânea."""
    def _aquecer():
        try:
            print("[Startup] Pré-aquecendo cache de capacidade da Excia em background...")
            CapacidadeAdapter().buscar_capacidade(CONFIG)
            print("[Startup] Cache de capacidade pronto e aquecido!")
        except Exception as e:
            print(f"[Startup] Aviso no pré-aquecimento de capacidade: {e}")

    threading.Thread(target=_aquecer, daemon=True).start()


# ── Servir o HTML ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "ui" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── Endpoint de identificação rápida (UX instantânea no upload) ─────────────
@app.post("/identificar")
async def endpoint_identificar(
    arquivo: UploadFile = File(...),
    campo: str = "desconhecido",
):
    """
    Recebe 1 arquivo + nome do campo (pedido/mrp/capacidade).
    Retorna {tipo, ok, mensagem} para feedback instantâneo na UI.
    Nunca retorna stacktrace — sempre mensagem amigável em pt-BR.
    """
    try:
        conteudo = await arquivo.read()
        ident = identificar_tipo(conteudo)
        tipo_esperado_map = {
            "pedido": TipoPDF.PEDIDO,
            "mrp": TipoPDF.MRP,
            "capacidade": TipoPDF.CAPACIDADE,
        }
        tipo_esperado = tipo_esperado_map.get(campo.lower())

        if ident.tipo == tipo_esperado:
            # Contagem prévia para feedback
            extra = ""
            if ident.tipo == TipoPDF.PEDIDO and ident.n_pedidos:
                extra = f" — {ident.n_pedidos} pedido(s) encontrado(s)"
            elif ident.tipo == TipoPDF.CAPACIDADE and ident.n_periodos:
                extra = f" — {ident.n_periodos} período(s) encontrado(s)"
            nome = TipoPDF.NOMES_AMIGAVEIS.get(ident.tipo, ident.tipo)
            return {"ok": True, "tipo": ident.tipo, "mensagem": f"✓ {nome} reconhecido{extra}"}

        # Tipo errado ou desconhecido → mensagem orientativa
        return {"ok": False, "tipo": ident.tipo, "mensagem": _msg_erro_tipo(ident, campo)}

    except Exception as exc:
        return {"ok": False, "tipo": "ERRO", "mensagem": f"Erro inesperado ao ler arquivo: {exc}"}


# ── Endpoint principal de análise ────────────────────────────────────────────
@app.post("/analisar")
async def endpoint_analisar(
    pedido: UploadFile = File(...),
    mrp: UploadFile = File(...),
    capacidade: UploadFile = File(...),
    mapa: Optional[UploadFile] = File(default=None),
):
    """
    Recebe os 3 PDFs obrigatórios (+ Mapa opcional).
    Retorna JSON com ResultadoAnalise.
    HTTP 200 sempre — erros aparecem em erros_entrada[] ou avisos_leitura[].
    """
    resultado = ResultadoAnalise(
        timestamp=date.today().isoformat(),
        data_analise=date.today(),
    )

    try:
        # Ler conteúdos
        bytes_pedido = await pedido.read()
        bytes_mrp = await mrp.read()
        bytes_cap = await capacidade.read()
        bytes_mapa = (await mapa.read()) if mapa else None

        # Validar tipos
        erros = []
        ident_pedido = identificar_tipo(bytes_pedido)
        ident_mrp = identificar_tipo(bytes_mrp)
        ident_cap = identificar_tipo(bytes_cap)

        if ident_pedido.tipo != TipoPDF.PEDIDO:
            erros.append({"campo": "pedido", "mensagem": _msg_erro_tipo(ident_pedido, "pedido")})
        if ident_mrp.tipo != TipoPDF.MRP:
            erros.append({"campo": "mrp", "mensagem": _msg_erro_tipo(ident_mrp, "mrp")})
        if ident_cap.tipo != TipoPDF.CAPACIDADE:
            erros.append({"campo": "capacidade", "mensagem": _msg_erro_tipo(ident_cap, "capacidade")})

        if erros:
            resultado.erros_entrada = erros
            return JSONResponse(content=_serializar(resultado))

        # Parsear
        try:
            pedidos_parsed = parse_pedido(bytes_pedido)
        except Exception as e:
            resultado.erros_entrada.append({
                "campo": "pedido",
                "mensagem": f"O arquivo foi identificado como Pedido, mas o conteúdo não pôde ser lido no layout esperado. Detalhes: {e}"
            })
            return JSONResponse(content=_serializar(resultado))

        try:
            mrp_parsed = parse_mrp(bytes_mrp)
        except Exception as e:
            resultado.erros_entrada.append({
                "campo": "mrp",
                "mensagem": f"O arquivo foi identificado como MRP, mas o conteúdo não pôde ser lido no layout esperado. Detalhes: {e}"
            })
            return JSONResponse(content=_serializar(resultado))

        try:
            cap_parsed = parse_capacidade(bytes_cap)
        except Exception as e:
            resultado.erros_entrada.append({
                "campo": "capacidade",
                "mensagem": f"O arquivo foi identificado como Capacidade, mas o conteúdo não pôde ser lido no layout esperado. Detalhes: {e}"
            })
            return JSONResponse(content=_serializar(resultado))

        # Validações pós-parse (sanidade — seção 5.4 do ROADMAP)
        if not pedidos_parsed:
            resultado.erros_entrada.append({
                "campo": "pedido",
                "mensagem": "O arquivo foi identificado como 'Emissão de Pedido', mas nenhum pedido com linhas foi lido. O layout do relatório pode ter mudado no Excia — contate o suporte da ferramenta."
            })
            return JSONResponse(content=_serializar(resultado))

        if not mrp_parsed:
            resultado.erros_entrada.append({
                "campo": "mrp",
                "mensagem": "O arquivo foi identificado como 'MRP', mas nenhum bloco de insumo foi lido. O layout do relatório pode ter mudado no Excia — contate o suporte da ferramenta."
            })
            return JSONResponse(content=_serializar(resultado))

        if len(cap_parsed.periodos) < 3:
            resultado.erros_entrada.append({
                "campo": "capacidade",
                "mensagem": "O arquivo foi identificado como 'Capacidade', mas menos de 3 períodos foram lidos. O layout do relatório pode ter mudado no Excia — contate o suporte da ferramenta."
            })
            return JSONResponse(content=_serializar(resultado))

        # Avisos de leitura (blocos com parse_ok=False no MRP)
        for bloco in mrp_parsed:
            if not bloco.parse_ok:
                resultado.avisos_leitura.append(
                    f"⚠️ Bloco MRP {bloco.cod_insumo} ({bloco.descricao}): "
                    + "; ".join(bloco.avisos_reconciliacao)
                )

        # Executar análise
        resultado = analisar(pedidos_parsed, mrp_parsed, cap_parsed, date.today(), CONFIG, resultado)

    except Exception as exc:
        resultado.avisos_leitura.append(f"Erro inesperado no servidor: {exc}")

    return JSONResponse(content=_serializar(resultado))


# ── Endpoint principal da Sprint 4 (Análise por Número) ──────────────────────
@app.post("/analisar-pedido")
async def endpoint_analisar_pedido(numero_pedido: str = Form(...)):
    """
    Novo fluxo da Sprint 4: recebe o número do pedido e resolve tudo via API.
    """
    try:
        resultado = analisar_pedido_por_numero(numero_pedido, CONFIG)
    except Exception as exc:
        hoje = date.today()
        resultado = ResultadoAnalise(timestamp=hoje.isoformat(), data_analise=hoje)
        resultado.avisos_leitura.append(f"Erro inesperado no servidor: {exc}")

    return JSONResponse(content=_serializar(resultado))


# ── Endpoint de demonstração com fixtures locais ─────────────────────────────
@app.get("/analisar-demo")
async def endpoint_analisar_demo():
    """
    Roda a análise usando as fixtures PDF locais da pasta tests/fixtures/.
    Evita a necessidade de fazer upload manual durante testes e demos rápidas.
    """
    resultado = ResultadoAnalise(
        timestamp=date.today().isoformat(),
        data_analise=date.today(),
    )

    path_ped = BASE_DIR / "tests" / "fixtures" / "pedidos.pdf"
    path_mrp = BASE_DIR / "tests" / "fixtures" / "mrp.pdf"
    path_cap = BASE_DIR / "tests" / "fixtures" / "capacidade.pdf"

    if not (path_ped.exists() and path_mrp.exists() and path_cap.exists()):
        resultado.erros_entrada.append({
            "campo": "sistema",
            "mensagem": "Arquivos de teste (fixtures) não localizados na pasta tests/fixtures/ do servidor."
        })
        return JSONResponse(content=_serializar(resultado))

    try:
        bytes_pedido = path_ped.read_bytes()
        bytes_mrp = path_mrp.read_bytes()
        bytes_cap = path_cap.read_bytes()

        pedidos_parsed = parse_pedido(bytes_pedido)
        mrp_parsed = parse_mrp(bytes_mrp)
        cap_parsed = parse_capacidade(bytes_cap)

        # Sanidade
        if not pedidos_parsed:
            resultado.erros_entrada.append({"campo": "pedido", "mensagem": "Nenhum pedido extraído do PDF de teste."})
            return JSONResponse(content=_serializar(resultado))
        if not mrp_parsed:
            resultado.erros_entrada.append({"campo": "mrp", "mensagem": "Nenhum insumo extraído do PDF de teste."})
            return JSONResponse(content=_serializar(resultado))
        if not cap_parsed.periodos:
            resultado.erros_entrada.append({"campo": "capacidade", "mensagem": "Nenhuma semana extraída do PDF de teste."})
            return JSONResponse(content=_serializar(resultado))

        # Avisos de leitura do MRP
        for bloco in mrp_parsed:
            if not bloco.parse_ok:
                resultado.avisos_leitura.append(
                    f"⚠️ Bloco MRP {bloco.cod_insumo} ({bloco.descricao}): "
                    + "; ".join(bloco.avisos_reconciliacao)
                )

        # Analisar
        resultado = analisar(pedidos_parsed, mrp_parsed, cap_parsed, date.today(), CONFIG, resultado)

    except Exception as exc:
        resultado.avisos_leitura.append(f"Erro inesperado na análise de demonstração: {exc}")

    return JSONResponse(content=_serializar(resultado))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _msg_erro_tipo(ident: Identificacao, campo: str) -> str:
    """Gera mensagem amigável de erro de tipo de PDF."""
    tipo_esperado_map = {
        "pedido": TipoPDF.PEDIDO,
        "mrp": TipoPDF.MRP,
        "capacidade": TipoPDF.CAPACIDADE,
    }
    nome_esperado_map = {
        "pedido": "Emissão de Pedido - Vendas",
        "mrp": "Relatório de Consumos - Detalhado",
        "capacidade": "Resumo por Período (Capacidade)",
    }
    tipo_esperado = tipo_esperado_map.get(campo.lower(), "")
    nome_esperado = nome_esperado_map.get(campo.lower(), tipo_esperado)

    if ident.tipo == TipoPDF.NAO_PDF or ident.tipo == TipoPDF.PDF_VAZIO:
        if ident.mensagem and "exporte" in ident.mensagem.lower():
            return ident.mensagem
        return (
            "Este arquivo não é um PDF válido ou está vazio. "
            "Exporte novamente do Excia em formato PDF."
        )

    if ident.tipo in (TipoPDF.PEDIDO, TipoPDF.MRP, TipoPDF.CAPACIDADE):
        nome_detectado = TipoPDF.NOMES_AMIGAVEIS.get(ident.tipo, ident.tipo)
        campo_correto = TipoPDF.CAMPOS_CORRETOS.get(ident.tipo, ident.tipo)
        return (
            f"O arquivo enviado no campo '{campo}' parece ser o relatório "
            f"'{nome_detectado}' do Excia. "
            f"Coloque-o no campo '{campo_correto}' e envie aqui o relatório '{nome_esperado}'."
        )

    return (
        f"Não reconhecemos este arquivo como o relatório '{nome_esperado}' esperado. "
        f"Confira se você exportou o relatório correto do Excia."
    )


def _serializar(obj) -> dict:
    """Serializa ResultadoAnalise (dataclasses com dates) para dict JSON-compatível."""
    import dataclasses

    def _conv(o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return {k: _conv(v) for k, v in dataclasses.asdict(o).items()}
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, list):
            return [_conv(i) for i in o]
        if isinstance(o, dict):
            return {k: _conv(v) for k, v in o.items()}
        return o

    return _conv(obj)


# ── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Copiloto PCP — Papinha Baby")
    print("  Acesse: http://localhost:8000")
    print("  Ctrl+C para encerrar")
    print("=" * 60)
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)

"""
parsers/validacao.py — Identificação do tipo de PDF por fingerprints.
REQUISITO DE PRODUTO: nenhum parser roda sem identificação positiva do tipo.
Nenhum stacktrace chega ao usuário — sempre mensagem amigável.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

from engine.models import TipoPDF


@dataclass
class Identificacao:
    """Resultado da identificação de tipo de um PDF."""
    tipo: str          # TipoPDF.*
    confianca: str     # ALTA | MEDIA | BAIXA
    n_pedidos: Optional[int] = None
    n_periodos: Optional[int] = None
    mensagem: str = ""


def identificar_tipo(pdf_bytes: bytes) -> Identificacao:
    """
    Identifica o tipo de PDF pelos fingerprints (seção 5.4 do ROADMAP).
    Retorna Identificacao com tipo ∈ {PEDIDO, MRP, CAPACIDADE, DESCONHECIDO, NAO_PDF, PDF_VAZIO}.
    Nunca lança exceção — erros viram Identificacao com tipo NAO_PDF.
    """
    # 1. Verificar magic bytes PDF
    if not pdf_bytes or not pdf_bytes[:4].startswith(b"%PDF"):
        return Identificacao(
            tipo=TipoPDF.NAO_PDF,
            confianca="ALTA",
            mensagem="Este arquivo não é um PDF válido. Exporte novamente do Excia em formato PDF."
        )

    # 2. Tentar abrir com pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return Identificacao(
                    tipo=TipoPDF.PDF_VAZIO,
                    confianca="ALTA",
                    mensagem="PDF válido mas sem páginas."
                )

            # Extrair texto das primeiras 2 páginas para fingerprint
            texto_p1 = (pdf.pages[0].extract_text() or "").lower()
            texto_p2 = (pdf.pages[1].extract_text() or "").lower() if len(pdf.pages) > 1 else ""
            texto_total = texto_p1 + "\n" + texto_p2

            if not texto_p1.strip():
                return Identificacao(
                    tipo=TipoPDF.PDF_VAZIO,
                    confianca="ALTA",
                    mensagem="PDF está vazio ou é um PDF de imagem sem texto. Exporte novamente do Excia em PDF."
                )

            # 3. Testar fingerprints por tipo
            return _detectar_tipo(pdf, texto_total, pdf_bytes)

    except Exception as exc:
        return Identificacao(
            tipo=TipoPDF.NAO_PDF,
            confianca="ALTA",
            mensagem=f"Não foi possível ler este arquivo como PDF: {exc}"
        )


def _detectar_tipo(pdf, texto: str, pdf_bytes: bytes) -> Identificacao:
    """Aplica as fingerprints definidas na seção 5.4 do ROADMAP."""

    # ── PEDIDO ─────────────────────────────────────────────────────────────
    # Primária: 'emissão de pedido - vendas' OU 'wespelhopf'
    # Secundária: ≥1 ocorrência de 'numero:' + 'ped. cliente:'
    if ("emissão de pedido - vendas" in texto or
            "emissao de pedido - vendas" in texto or
            "wespelhopf" in texto):
        if "numero:" in texto and ("ped. cliente:" in texto or "ped.cliente:" in texto):
            # Contar pedidos
            import re
            n_pedidos = len(re.findall(r"numero:\s*\d+", texto, re.IGNORECASE))
            return Identificacao(
                tipo=TipoPDF.PEDIDO,
                confianca="ALTA",
                n_pedidos=max(n_pedidos, 1),
                mensagem=f"Relatório de Pedidos reconhecido — {n_pedidos} pedido(s) encontrado(s)"
            )
        # Primária bateu mas secundária não — confiança média
        return Identificacao(
            tipo=TipoPDF.PEDIDO,
            confianca="MEDIA",
            mensagem="Relatório de Pedidos identificado (confirmação parcial)"
        )

    # ── MRP ────────────────────────────────────────────────────────────────
    # Primária: 'relatório de consumos - detalhado' OU 'wpcpmatcons3'
    # Secundária: cabeçalho com 'consumo' + 'estoque' + 'saldo'
    if ("relatório de consumos - detalhado" in texto or
            "relatorio de consumos - detalhado" in texto or
            "wpcpmatcons3" in texto or
            "relatório de consumos" in texto):
        if ("consumo" in texto and "estoque" in texto and "saldo" in texto):
            return Identificacao(
                tipo=TipoPDF.MRP,
                confianca="ALTA",
                mensagem="Relatório de Consumos (MRP) reconhecido"
            )
        return Identificacao(
            tipo=TipoPDF.MRP,
            confianca="MEDIA",
            mensagem="Relatório de Consumos identificado (confirmação parcial)"
        )

    # ── CAPACIDADE ─────────────────────────────────────────────────────────
    # Primária: 'resumo por' + 'quant. pend'
    # Secundária: ≥3 linhas no padrão \d{4}\s+[\d.]+
    if "resumo por" in texto and ("quant. pend" in texto or "quant.pend" in texto or "quant pend" in texto):
        import re
        # Contar períodos AASS (4 dígitos seguidos de número)
        periodos = re.findall(r"\b\d{4}\b", texto)
        # Filtrar apenas períodos plausíveis (2600-2799)
        periodos_validos = [int(p) for p in periodos if 2600 <= int(p) <= 2799]
        n_periodos = len(set(periodos_validos))
        if n_periodos >= 3:
            return Identificacao(
                tipo=TipoPDF.CAPACIDADE,
                confianca="ALTA",
                n_periodos=n_periodos,
                mensagem=f"Relatório de Capacidade reconhecido — {n_periodos} período(s)"
            )
        # Poucos períodos — confiança baixa
        return Identificacao(
            tipo=TipoPDF.CAPACIDADE,
            confianca="BAIXA",
            mensagem="Relatório de Capacidade identificado mas com poucos dados"
        )

    # ── DESCONHECIDO ───────────────────────────────────────────────────────
    return Identificacao(
        tipo=TipoPDF.DESCONHECIDO,
        confianca="ALTA",
        mensagem="Não reconhecemos este arquivo como um dos relatórios do Excia esperados."
    )

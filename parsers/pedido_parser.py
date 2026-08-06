"""
parsers/pedido_parser.py — Parser do PDF "Emissão de Pedido - Vendas".
Estratégia: extrair texto por página, segmentar por 'Numero: XXXXX', capturar por regex.
Grade de tamanhos DINÂMICA — lê cabeçalhos de coluna, nunca assume tamanhos fixos.

Layout real observado no PDF:
  - Cabeçalho: 'OrdemArtigo Descricao Cor PP P M G GG Qtde' (sem espaço entre Ordem e Artigo)
  - Linha de item: '1 4104040 / REGATA ANDREA 00088 - VERDE MUSGO 319 641 728 634 379 2.701'
"""

from __future__ import annotations

import io
import re
from typing import Optional

import pdfplumber

from engine.models import LinhaPedido, Pedido
from parsers.comum import parse_data_br, parse_num_br


# ── Expressões regulares ───────────────────────────────────────────────────

# Delimitador de bloco de pedido
_RE_NUMERO = re.compile(r"Numero:\s*(\d+)", re.IGNORECASE)

# Campos de cabeçalho do pedido
_RE_PED_CLIENTE = re.compile(r"Ped\.\s*Cliente:\s*(\d+)", re.IGNORECASE)
_RE_EMISSAO = re.compile(r"Emiss[aã]o:\s*([\d/]+)", re.IGNORECASE)
_RE_ENTREGA = re.compile(r"Entrega:\s*([\d/]+)", re.IGNORECASE)
_RE_CLIENTE = re.compile(r"(?:^|\n)Cliente:\s*(.+?)(?=\s{2,}|\n|\r|CNPJ|$)", re.IGNORECASE)
_RE_COLECAO = re.compile(r"Cole[çc][aã]o:\s*(.+?)(?=\s{2,}|$)", re.IGNORECASE)

# Tamanhos conhecidos para filtrar do cabeçalho
_TAMANHOS_VALIDOS = re.compile(
    r"^(PP|XGG|XG|GG|G|M|P|RN|UN|P\d+|G\d+|\d+[Nn]?)$",
    re.IGNORECASE
)

# Linha de item: "1 4104040 / REGATA ANDREA 00088 - VERDE MUSGO 319 641 728 634 379 2.701"
# Artigo 7 dígitos, separado por '/'
# Observação: o PDF usa apenas 1 espaço entre descrição e código de cor!
_RE_LINHA_ITEM = re.compile(
    r"^(\d{1,3})\s+"          # ordem
    r"(\d{7})(?:\s*/)?\s+"    # artigo (7 dígitos) + opcional '/'
    r"(.+?)\s+"               # descrição (espaço simples é suficiente)
    r"(\d{5})\s*[-–]\s*"     # código cor (5 dígitos) + ' - '
    r"(.+?)\s+"               # nome da cor
    r"([\d.,\s]+(?:[a-zA-Z]*[\d.,\s]*)*)$", # números (tamanhos + total + extras)
    re.IGNORECASE
)


def parse_pedido(pdf_bytes: bytes) -> list[Pedido]:
    """
    Extrai todos os pedidos do PDF "Emissão de Pedido - Vendas".
    Retorna lista de Pedido, cada um com N linhas de item.
    """
    texto_completo = _extrair_texto(pdf_bytes)
    blocos = _segmentar_blocos(texto_completo)
    pedidos = []
    for bloco_texto in blocos:
        pedido = _parse_bloco(bloco_texto)
        if pedido:
            pedidos.append(pedido)
    return pedidos


def _extrair_texto(pdf_bytes: bytes) -> str:
    partes = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                partes.append(t)
    return "\n".join(partes)


def _segmentar_blocos(texto: str) -> list[str]:
    posicoes = [m.start() for m in _RE_NUMERO.finditer(texto)]
    if not posicoes:
        return []
    blocos = []
    for i, pos in enumerate(posicoes):
        fim = posicoes[i + 1] if i + 1 < len(posicoes) else len(texto)
        blocos.append(texto[pos:fim])
    return blocos


def _parse_bloco(bloco: str) -> Optional[Pedido]:
    avisos = []

    m = _RE_NUMERO.search(bloco)
    if not m:
        return None
    numero = m.group(1)

    m_pc = _RE_PED_CLIENTE.search(bloco)
    ped_cliente = m_pc.group(1) if m_pc else ""

    m_em = _RE_EMISSAO.search(bloco)
    if not m_em:
        return None
    try:
        emissao = parse_data_br(m_em.group(1))
    except ValueError:
        return None

    m_en = _RE_ENTREGA.search(bloco)
    if not m_en:
        return None
    try:
        entrega = parse_data_br(m_en.group(1))
    except ValueError:
        return None

    m_cl = _RE_CLIENTE.search(bloco)
    cliente = m_cl.group(1).strip() if m_cl else ""

    m_col = _RE_COLECAO.search(bloco)
    colecao = m_col.group(1).strip() if m_col else ""

    linhas = _parse_linhas_item(bloco, numero, avisos)

    return Pedido(
        numero=numero,
        ped_cliente=ped_cliente,
        emissao=emissao,
        entrega=entrega,
        cliente=cliente,
        colecao=colecao,
        linhas=linhas,
        avisos_parsing=avisos,
    )


def _parse_linhas_item(bloco: str, numero: str, avisos: list) -> list[LinhaPedido]:
    linhas_texto = bloco.splitlines()
    tamanhos: list[str] = []
    idx_cabecalho = -1

    # Procurar linha de cabeçalho com tamanhos
    # Layout real: "OrdemArtigo Descricao Cor PP P M G GG Qtde"
    for i, linha in enumerate(linhas_texto):
        linha_stripped = linha.strip()
        # Detectar linha de cabeçalho: contém "Ordem" e "Artigo" e "Qtde" e tamanhos
        if re.search(r"Ordem\s*Artigo", linha_stripped, re.IGNORECASE) and \
           re.search(r"Qtde", linha_stripped, re.IGNORECASE):
            # Extrair tokens entre "Cor" e "Qtde"
            m_cor = re.search(r"Cor\s+(.+?)\s+Qtde", linha_stripped, re.IGNORECASE)
            if m_cor:
                grade_str = m_cor.group(1).strip()
                tamanhos = [
                    t.strip() for t in grade_str.split()
                    if _TAMANHOS_VALIDOS.match(t.strip())
                ]
            idx_cabecalho = i
            break

    # Processar linhas após o cabeçalho
    resultado = []
    inicio = idx_cabecalho + 1 if idx_cabecalho >= 0 else 0

    for linha in linhas_texto[inicio:]:
        linha = linha.strip()
        if not linha:
            continue
        if re.match(r"(observa[cç][aã]o|totais|desconto|total do pedido)", linha, re.IGNORECASE):
            continue

        item = _parse_linha_item_unica(linha, tamanhos, numero, avisos)
        if item:
            resultado.append(item)

    return resultado


def _parse_linha_item_unica(
    linha: str,
    tamanhos: list[str],
    numero: str,
    avisos: list,
) -> Optional[LinhaPedido]:
    """
    Parseia uma linha de item do pedido.
    Formato real: '1 4104040 / REGATA ANDREA 00088 - VERDE MUSGO 319 641 728 634 379 2.701'
    """
    m = _RE_LINHA_ITEM.match(linha)
    if not m:
        return None

    ordem = m.group(1)
    artigo = m.group(2)
    descricao = m.group(3).strip()
    cod_cor = m.group(4)
    nome_cor = m.group(5).strip()
    nums_str = m.group(6).strip()

    # Parsear números
    nums = []
    for tok in nums_str.split():
        try:
            nums.append(int(parse_num_br(tok)))
        except ValueError:
            continue

    if len(nums) < 1:
        return None

    total = nums[-1]
    qtds = nums[:-1]

    # Montar grade com tamanhos detectados
    grade = {}
    if tamanhos and len(qtds) == len(tamanhos):
        grade = dict(zip(tamanhos, qtds))
    elif qtds:
        grade = {str(i + 1): q for i, q in enumerate(qtds)}
        avisos.append(f"Pedido {numero} artigo {artigo}: tamanhos não detectados")

    # Validar soma
    soma = sum(grade.values())
    if abs(soma - total) > 0:
        avisos.append(
            f"Pedido {numero} artigo {artigo}: soma da grade ({soma}) ≠ total ({total})"
        )

    return LinhaPedido(
        ordem=ordem,
        codigo=artigo,
        descricao=descricao,
        cor=cod_cor,
        desc_cor=nome_cor,
        grade={k: float(v) for k, v in grade.items()},
        qtde_total=float(total),
    )


def _parse_linhas_item_alternativo(bloco: str, numero: str, avisos: list) -> list[LinhaPedido]:
    """
    Abordagem alternativa para layouts diferentes.
    Busca padrão: 7 dígitos de artigo + números ao final da linha.
    """
    linhas = []
    for linha in bloco.splitlines():
        linha = linha.strip()
        if not linha:
            continue

        # Procurar artigo de 7 dígitos
        m_art = re.search(r"\b(\d{7})\b", linha)
        if not m_art:
            continue

        artigo = m_art.group(1)

        # Procurar código de cor (5 dígitos precedido de espaço)
        m_cor = re.search(r"\b(\d{5})\b", linha[m_art.end():])
        if not m_cor:
            continue

        cod_cor = m_cor.group(1)

        # Números ao final
        nums_str = linha[m_art.end():].strip()
        nums = []
        for tok in re.findall(r"[\d.,]+", nums_str):
            try:
                nums.append(int(parse_num_br(tok)))
            except ValueError:
                continue

        if len(nums) < 2:
            continue

        total = nums[-1]
        qtds = nums[:-1]
        grade = {str(i + 1): q for i, q in enumerate(qtds)}

        linhas.append(LinhaPedido(
            ordem="1",
            codigo=artigo,
            descricao="",
            cor=cod_cor,
            desc_cor="",
            grade={k: float(v) for k, v in grade.items()},
            qtde_total=float(total),
        ))

    return linhas

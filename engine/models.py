"""
engine/models.py — Dataclasses do domínio do PCP.
Nenhuma lógica aqui — só estruturas de dados tipadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ──────────────────────────────────────────────
# Pedido de Vendas
# ──────────────────────────────────────────────

@dataclass
class LinhaPedido:
    """Uma linha de item dentro de um pedido (artigo + cor + grade)."""
    ordem: str
    codigo: str           # código do artigo (ex: '4104040')
    descricao: str
    cor: str
    desc_cor: str
    grade: dict[str, float]  # {'2': 319.0, '3': 641.0, ...}
    qtde_total: float
    dt_entrega_item: Optional[date] = None
    fluxo_id: Optional[str] = None
    qtde_faturada: float = 0.0


@dataclass
class Pedido:
    """Um bloco 'Numero: XXXXX' do PDF de Pedidos."""
    numero: str           # ex: '102559'
    ped_cliente: str
    emissao: date
    entrega: date
    cliente: str
    colecao: str
    linhas: list[LinhaPedido] = field(default_factory=list)

    # Avisos de parsing específicos deste pedido
    avisos_parsing: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# MRP — Relatório de Consumos
# ──────────────────────────────────────────────

@dataclass
class ProdutoMRP:
    """Linha de produto (OF) dentro de um bloco de insumo no MRP."""
    of: str               # número da OF (6 dígitos)
    cod_artigo: str       # código do artigo (7 dígitos)
    descricao: str
    setor_atual: str
    consumo: float
    aloc_estoque: float
    aloc_compra: float
    aloc_tecelagem: float
    aloc_pend_tint: float
    aloc_tinturaria: float
    saldo: float
    parse_ok: bool = True
    avisos: list[str] = field(default_factory=list)


@dataclass
class BlocoInsumo:
    """Um bloco de insumo agregado no MRP (linha agregada + N linhas de produto)."""
    cod_insumo: str       # 8 dígitos
    descricao: str
    un: str
    cod_cor: str
    nome_cor: str
    consumo: float
    estoque: float
    compra: float
    tecelagem: float
    pend_tint: float
    tinturaria: float
    saldo: float
    produtos: list[ProdutoMRP] = field(default_factory=list)
    parse_ok: bool = True
    avisos_reconciliacao: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# Capacidade Semanal
# ──────────────────────────────────────────────

@dataclass
class CapacidadeSemanal:
    """Dados do relatório de Resumo por Período."""
    periodos: dict[int, int]  # {aass: qtd_pendente}
    data_relatorio: Optional[date] = None


# ──────────────────────────────────────────────
# Resultado de matching Pedido ↔ MRP
# ──────────────────────────────────────────────

@dataclass
class MatchInsumo:
    """Insumo de um produto resultante do matching com o MRP."""
    cod_insumo: str
    descricao: str
    un: str
    cod_cor: str
    nome_cor: str
    necessario: float      # consumo deste produto (aloc total)
    aloc_estoque: float
    aloc_compra: float
    aloc_tecelagem: float
    aloc_pend_tint: float
    aloc_tinturaria: float
    saldo: float
    # Avaliação de status
    status: str = ""       # OK_ESTOQUE | OK_FUTURO | FALTA
    disponivel_em: Optional[date] = None
    fase_consumo: str = "CORTE"
    bloqueante: bool = False
    cor_divergente: bool = False
    avisos: list[str] = field(default_factory=list)


@dataclass
class MatchPedido:
    """Resultado do matching de uma linha de pedido com o MRP."""
    cod_artigo: str
    of: str
    confianca: str         # Detecção e rastreamento de OF oficial no Excia
    of_emitida: bool = False
    numero_of: Optional[str] = None
    semana_of_oficial: Optional[int] = None
    dt_emissao_of: Optional[date] = None
    setor_atual_of: Optional[str] = None
    qtde_of_oficial: Optional[int] = None

    # Resultado da Regra 3 (Insumos)
    insumos: list[MatchInsumo] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tecido_principal_encontrado: bool = False


# ──────────────────────────────────────────────
# Cronograma Draft
# ──────────────────────────────────────────────

@dataclass
class FaseCronograma:
    """Uma fase do cronograma draft de produção."""
    nome: str
    inicio: date
    fim: date
    dias: int


@dataclass
class Cronograma:
    """Cronograma draft completo de produção de uma linha de pedido."""
    fases: list[FaseCronograma] = field(default_factory=list)
    rota_detectada: str = "DEFAULT"
    pcp_dias: int = 21
    data_fim: Optional[date] = None
    semana_fim_aass: int = 0
    inicio_mais_tarde: Optional[date] = None
    folga_dias: int = 0


# ──────────────────────────────────────────────
# Resultado da análise de capacidade por pedido
# ──────────────────────────────────────────────

@dataclass
class AnaliseCapacidade:
    """Resultado da checagem de capacidade para uma linha de pedido."""
    semana_alvo: int          # AASS
    qtd_of: int               # qtde com buffer (+7%)
    semanas_relevantes: list[dict] = field(default_factory=list)
    # semanas_relevantes: [{aass, pend_atual, mais_este_pedido, limite, situacao}]
    cabe_no_alvo: bool = False
    semana_sugerida: Optional[int] = None
    avisos: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# Resultado final de análise por linha de pedido
# ──────────────────────────────────────────────

@dataclass
class CardPedido:
    """Card de resultado para exibição na UI — um por linha de pedido."""
    numero_pedido: str
    artigo: str
    descricao: str
    cod_cor: str
    nome_cor: str
    qtde_pedido: int
    qtd_of: int
    entrega_cliente: date
    semana_alvo: int         # AASS
    veredito: str            # VERDE | AMARELO | VERMELHO
    motivos: list[str]
    match: Optional[MatchPedido]
    insumos: list[MatchInsumo]
    cronograma: Optional[Cronograma]
    capacidade: Optional[AnaliseCapacidade]
    sugestao: str
    sugestao_semana: Optional[int]
    # Rastreamento de OF emitida no Excia
    of_emitida: bool = False
    numero_of: Optional[str] = None
    semana_of_oficial: Optional[int] = None
    dt_emissao_of: Optional[date] = None
    setor_atual_of: Optional[str] = None
    qtde_of_oficial: Optional[int] = None
    horizonte_longo: bool = False
    avisos_flags: list[str] = field(default_factory=list)
    dados_brutos: dict = field(default_factory=dict)  # para <details> de auditoria
    qtde_faturada: int = 0


# ──────────────────────────────────────────────
# Resultado global da análise
# ──────────────────────────────────────────────

@dataclass
class ResultadoAnalise:
    """Resultado completo retornado pelo endpoint /analisar."""
    timestamp: str
    data_analise: date
    alertas_globais: list[str] = field(default_factory=list)
    avisos_leitura: list[str] = field(default_factory=list)
    erros_entrada: list[dict] = field(default_factory=list)  # [{campo, mensagem}]
    pedidos: list[CardPedido] = field(default_factory=list)


# ──────────────────────────────────────────────
# Tipos de PDF (validação)
# ──────────────────────────────────────────────

class TipoPDF:
    PEDIDO = "PEDIDO"
    MRP = "MRP"
    CAPACIDADE = "CAPACIDADE"
    DESCONHECIDO = "DESCONHECIDO"
    NAO_PDF = "NAO_PDF"
    PDF_VAZIO = "PDF_VAZIO"

    NOMES_AMIGAVEIS = {
        "PEDIDO": "Emissão de Pedido - Vendas",
        "MRP": "Relatório de Consumos - Detalhado",
        "CAPACIDADE": "Resumo por Período (Capacidade)",
    }

    CAMPOS_CORRETOS = {
        "PEDIDO": "pedido",
        "MRP": "mrp",
        "CAPACIDADE": "capacidade",
    }

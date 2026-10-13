"""
api/setor_adapter.py — Gerenciamento e resolução dinâmica de Lead Times dos Setores.
Expõe gerar_sugestao() para o Copiloto e mantém SetorAdapter para consulta à API Excia.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, List, Tuple
import yaml

from engine.models import SugestaoLeadTime
from engine.persistencia_lead_time import buscar_ultimo
from .excia_client import ExciaAPIClient

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DEFAULT_SUGERIDOS_YAML = CONFIG_DIR / "lead_times_sugeridos.yaml"

_CACHE_SUGERIDOS: Optional[Dict[str, Tuple[int, int]]] = None


ALIASES_SETORES = {
    "ESTAMPA NUCA": "ESTAMPARIA_NUCA",
    "ESTAMPARIA NUCA": "ESTAMPARIA_NUCA",
    "QUAL. ESTAMPARIA": "QUAL_ESTAMPARIA",
    "QUAL. ESTAMPARIA NUCA": "QUAL_ESTAMPARIA_NUCA",
    "QUAL. COSTURA": "QUAL_COSTURA",
    "QUAL. LAVANDERIA": "QUAL_LAVANDERIA",
    "QUAL. APLIQUE": "QUAL_APLIQUE",
    "QUAL. ENTRETELA": "QUAL_ENTRETELA",
    "ACAB. COST.": "ACAB_COST",
    "ACAB. COSTURA": "ACAB_COST",
    "QUAL. ACABAMENTOS COSTURA": "QUAL_ACABAMENTOS_COSTURA",
    "QUAL.": "QUAL",
    "CASEADO/BOTAO": "CASEADO_BOTAO",
    "PRE PASSADORIA/REVISAO/EMBALAG": "PRE_PASSADORIA_REVISAO_EMBALAG",
}


def normalizar_nome_setor(nome: str) -> str:
    """Normaliza nome de setor para correspondência consistente."""
    if not nome:
        return ""
    n = (
        nome.strip()
        .upper()
        .replace("Ã", "A")
        .replace("Õ", "O")
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
        .replace("Ç", "C")
    )
    if n in ALIASES_SETORES:
        return ALIASES_SETORES[n]
    n_sub = n.replace(".", "").replace("  ", " ").strip()
    if n_sub in ALIASES_SETORES:
        return ALIASES_SETORES[n_sub]
    return n


def _carregar_sugeridos_yaml(yaml_path: Optional[Path | str] = None) -> Dict[str, Tuple[int, int]]:
    global _CACHE_SUGERIDOS
    caminho = Path(yaml_path) if yaml_path else DEFAULT_SUGERIDOS_YAML

    if yaml_path is None and _CACHE_SUGERIDOS is not None:
        return _CACHE_SUGERIDOS

    if not caminho.exists():
        return {}

    with open(caminho, encoding="utf-8") as f:
        dados = yaml.safe_load(f) or {}

    setores_raw = dados.get("setores", {})
    normalizados: Dict[str, Tuple[int, int]] = {}
    for k, v in setores_raw.items():
        k_norm = normalizar_nome_setor(k)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            normalizados[k_norm] = (int(v[0]), int(v[1]))
        elif isinstance(v, (int, float)):
            normalizados[k_norm] = (int(v), int(v))

    if yaml_path is None:
        _CACHE_SUGERIDOS = normalizados
    return normalizados


def gerar_sugestao(
    codigo_artigo: str,
    setor: str,
    db_path: Optional[Path | str] = None,
    yaml_path: Optional[Path | str] = None,
) -> SugestaoLeadTime:
    """
    Gera sugestão de lead time para um setor e artigo.
    1. Consulta histórico confirmado para este artigo em data/lead_times_confirmados.sqlite
    2. Cai para config/lead_times_sugeridos.yaml (origem="generico")
    3. Se não encontrar, retorna dias_min=0, dias_max=0, origem="sem_sugestao"
    """
    if not setor:
        return SugestaoLeadTime(dias_min=0, dias_max=0, origem="sem_sugestao")

    setor_norm = normalizar_nome_setor(setor)

    # 1. Histórico confirmado
    if codigo_artigo:
        ultimo = buscar_ultimo(codigo_artigo, setor_norm, db_path=db_path)
        if ultimo:
            return ultimo

    # 2. Cadastro de sugeridos em YAML
    sugeridos = _carregar_sugeridos_yaml(yaml_path)
    if setor_norm in sugeridos:
        faixa = sugeridos[setor_norm]
        return SugestaoLeadTime(dias_min=faixa[0], dias_max=faixa[1], origem="generico")

    # 3. Sem sugestão (correspondência estritamente exata, sem substring)
    return SugestaoLeadTime(dias_min=0, dias_max=0, origem="sem_sugestao")



class SetorAdapter:
    """
    Adapter para obter setores da API Excia e gerar sugestões de lead time.
    """
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()
        self._cache_setores: Optional[List[dict]] = None

    def obter_setores(self) -> List[dict]:
        """Consulta SetorLista na API Excia."""
        if self._cache_setores is not None:
            return self._cache_setores

        try:
            res = self.client.get("SetorLista")
            if isinstance(res, list):
                self._cache_setores = res
                return res
        except Exception:
            pass

        self._cache_setores = []
        return self._cache_setores

    def gerar_sugestao(self, codigo_artigo: str, setor: str) -> SugestaoLeadTime:
        return gerar_sugestao(codigo_artigo, setor)

    def obter_lead_time_fase(self, nome_fase: str, pcp_override: Optional[int] = None) -> int:
        """
        Método de compatibilidade para obter lead time em dias úteis.
        """
        if not nome_fase:
            return 1

        n = normalizar_nome_setor(nome_fase)
        if "PCP" in n and pcp_override is not None:
            return pcp_override

        sug = gerar_sugestao("", nome_fase)
        if sug.origem != "sem_sugestao" and sug.dias_min > 0:
            return sug.dias_min

        return 1

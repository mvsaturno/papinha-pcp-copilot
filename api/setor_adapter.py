"""
api/setor_adapter.py — Gerenciamento e resolução dinâmica de Lead Times dos Setores.
Consulta a API Excia para obter os setores cadastrados e determina a duração (dias úteis) de cada fase do cronograma.
"""

from typing import Dict, Optional, List
from .excia_client import ExciaAPIClient


# Lead times padrão dos setores (em dias úteis) calibrados com o PCP da Papinha Baby
_LEAD_TIMES_PADRAO_SETORES: Dict[str, int] = {
    "PCP": 2,
    "TECELAGEM": 5,
    "TINTURARIA": 20,
    "ENCAIXE": 1,
    "CORTE": 4,
    "ENTRETELA": 2,
    "QUAL_ENTRETELA": 1,
    "ESTAMPARIA": 5,
    "ESTAMPARIA_NUCA": 4,
    "ESTAMPA NUCA": 4,
    "QUAL_ESTAMPARIA": 1,
    "CQ": 1,
    "QUAL_APLIQUE": 1,
    "APLIQUE": 8,
    "LAVANDERIA": 10,
    "QUAL_LAVANDERIA": 1,
    "COSTURA": 11,
    "QUAL_COSTURA": 1,
    "ACAB_COST": 4,
    "QUAL": 1,
    "CASEADO_BOTAO": 3,
    "PASSADORIA": 4,
    "REVISAO": 6,
    "EMBALAGEM": 4,
}


class SetorAdapter:
    """
    Adapter para obter dinamicamente os setores e seus lead times da API Excia.
    """
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()
        self._cache_setores: Optional[List[dict]] = None
        self._lead_times_cache: Dict[str, int] = dict(_LEAD_TIMES_PADRAO_SETORES)

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

    def obter_lead_time_fase(self, nome_fase: str, pcp_override: Optional[int] = None) -> int:
        """
        Retorna a duração em dias úteis para uma fase/setor da produção.
        """
        if not nome_fase:
            return 1

        n = nome_fase.strip().upper().replace("Ã", "A").replace("Ó", "O").replace("É", "E").replace("Á", "A")

        if "PCP" in n:
            return pcp_override if pcp_override is not None else self._lead_times_cache.get("PCP", 2)
        if "TECELAGEM" in n:
            return self._lead_times_cache.get("TECELAGEM", 5)
        if "TINTURARIA" in n:
            return self._lead_times_cache.get("TINTURARIA", 20)
        if "ENCAIXE" in n and "AGUARDANDO" not in n:
            return self._lead_times_cache.get("ENCAIXE", 1)
        if "CORTE" in n and "CD" not in n:
            return self._lead_times_cache.get("CORTE", 4)
        if "ENTRETELA" in n:
            return self._lead_times_cache.get("QUAL_ENTRETELA", 1) if "QUAL" in n else self._lead_times_cache.get("ENTRETELA", 2)
        if "COSTURA" in n and "QUAL" not in n and "PRE" not in n and "ACAB" not in n:
            return self._lead_times_cache.get("COSTURA", 11)
        if "LAVANDERIA" in n or "LAVACAO" in n:
            return self._lead_times_cache.get("QUAL_LAVANDERIA", 1) if ("QUAL" in n or "PRE" in n) else self._lead_times_cache.get("LAVANDERIA", 10)
        if "APLIQUE" in n:
            return self._lead_times_cache.get("QUAL_APLIQUE", 1) if ("QUAL" in n or "PRE" in n) else self._lead_times_cache.get("APLIQUE", 8)
        if "ESTAMPARIA NUCA" in n or "ESTAMPA NUCA" in n:
            return self._lead_times_cache.get("ESTAMPARIA_NUCA", 4)
        if "ESTAMPARIA" in n or "ESTAMPA" in n:
            return self._lead_times_cache.get("QUAL_ESTAMPARIA", 1) if ("QUAL" in n or "PRE" in n) else self._lead_times_cache.get("ESTAMPARIA", 5)
        if "ACAB" in n:
            return self._lead_times_cache.get("ACAB_COST", 4)
        if "PASSADORIA" in n:
            return self._lead_times_cache.get("PASSADORIA", 4)
        if "REVISAO" in n:
            return self._lead_times_cache.get("REVISAO", 6)
        if "EMBALAGEM" in n:
            return self._lead_times_cache.get("EMBALAGEM", 4)
        if "CASEADO" in n or "BOTAO" in n or "BOTÃO" in n:
            return self._lead_times_cache.get("CASEADO_BOTAO", 3)
        if "QUAL" in n or "CQ" in n:
            return 1

        # Fallback para valor cadastrado ou 1 dia
        for k, v in self._lead_times_cache.items():
            if k in n:
                return v

        return 1

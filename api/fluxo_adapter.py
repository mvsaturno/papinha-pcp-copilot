from typing import Optional
from .excia_client import ExciaAPIClient

class FluxoAdapter:
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()
        self._cache = {} # Cache in memory to avoid querying the same route multiple times per run

    def buscar_todas_partes_produto(self, codigo_produto: str) -> list[dict]:
        """
        Consulta a API ParteProdutoLista e busca os fluxos e fases de todas as partes do artigo.
        Retorna lista de partes: [{'parte': '01', 'descricao': 'SUPERIOR', 'fluxo': '329', 'principal': True, 'fases': [...]}, ...]
        """
        if not codigo_produto:
            return []

        cache_key = f"produto_partes_{codigo_produto}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            response = self.client.get("ParteProdutoLista", params={"codigo": codigo_produto})
            if not response or not isinstance(response, list):
                self._cache[cache_key] = []
                return []

            partes = []
            for p in response:
                fid = str(p.get("fluxo", "")).strip()
                if not fid:
                    continue
                fases = self.buscar_fases(fid) or []
                partes.append({
                    "parte": str(p.get("parte", "")).strip(),
                    "descricao": str(p.get("descricao", "")).strip().upper(),
                    "fluxo": fid,
                    "principal": str(p.get("principal", "")).upper() == "S",
                    "fases": fases,
                })

            self._cache[cache_key] = partes
            return partes
        except Exception:
            self._cache[cache_key] = []
            return []

    def buscar_fluxo_do_produto(self, codigo_produto: str) -> Optional[str]:
        """
        Consulta a API ParteProdutoLista para descobrir o código do fluxo principal do artigo.
        Prioriza a parte marcada com principal='S' ou '00' ou '01'.
        """
        if not codigo_produto:
            return None

        partes = self.buscar_todas_partes_produto(codigo_produto)
        if not partes:
            return None

        # 1. Procurar parte principal='S'
        for p in partes:
            if p.get("principal"):
                return p["fluxo"]

        # 2. Procurar parte '00' ou '01'
        for p in partes:
            if p.get("parte") in ("00", "01"):
                return p["fluxo"]

        # 3. Fallback: primeira parte válida
        return partes[0]["fluxo"]

    def buscar_fases(self, codigo_fluxo: str) -> Optional[list[str]]:
        """
        Consulta a API de Fluxo e retorna uma lista ordenada de descrições dos setores.
        Filtra etapas de buffer/transição para manter as etapas produtivas reais do Excia.
        """
        if not codigo_fluxo:
            return None
            
        if codigo_fluxo in self._cache:
            return self._cache[codigo_fluxo]

        try:
            response = self.client.get(f"Fluxo/{codigo_fluxo}")
            
            if not response or not isinstance(response, list) or len(response) == 0:
                self._cache[codigo_fluxo] = None
                return None
                
            fluxo_data = response[0]
            setores = fluxo_data.get("setores", [])
            
            if not setores:
                self._cache[codigo_fluxo] = None
                return None
                
            # Ordenar pelo campo "ordem"
            setores_ordenados = sorted(setores, key=lambda s: s.get("ordem", 999))
            
            # Extrair etapas oficiais que compõem o cronograma da OF no Excia
            fases = []
            for s in setores_ordenados:
                desc = s.get("descricao", "").strip().upper()
                if not desc:
                    continue
                # Descartar setores de fila/espera que não compõem a tabela de cronograma da OF
                if desc.startswith("PRE ") or desc.startswith("AGUARDANDO") or desc.startswith("CD ") or desc == "DESENVOLVIMENTO":
                    continue
                # Padronizar nomes conforme o relatório do Excia
                if "QUAL" in desc and "ACAB" in desc:
                    desc = "QUAL."
                elif "QUAL" in desc and "ESTAMPA" in desc:
                    desc = "QUAL. ESTAMPARIA"
                elif desc == "PRE REVISÃO/EMBALAGEM" or desc == "PRE PASSADORIA/REVISÃO/EMBALAG":
                    continue
                fases.append(desc)
            
            self._cache[codigo_fluxo] = fases
            return fases
            
        except Exception:
            self._cache[codigo_fluxo] = None
            return None

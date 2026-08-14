from typing import Optional
from .excia_client import ExciaAPIClient

class FluxoAdapter:
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()
        self._cache = {} # Cache in memory to avoid querying the same route multiple times per run

    def buscar_fluxo_do_produto(self, codigo_produto: str) -> Optional[str]:
        """
        Consulta a API ParteProdutoLista para descobrir o código do fluxo atrelado ao artigo.
        Retorna o código do fluxo (ex: '340') ou None se não encontrar.
        """
        if not codigo_produto:
            return None
            
        cache_key = f"produto_fluxo_{codigo_produto}"
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        try:
            response = self.client.get("ParteProdutoLista", params={"codigo": codigo_produto})
            if response and isinstance(response, list) and len(response) > 0:
                # Vamos pegar a parte '00' (principal) se houver várias, ou a primeira que tiver fluxo
                fluxo = None
                for parte in response:
                    if parte.get("fluxo"):
                        fluxo = str(parte.get("fluxo"))
                        if parte.get("parte") == "00":
                            break # Encontramos a parte principal com fluxo
                
                if fluxo:
                    self._cache[cache_key] = fluxo
                    return fluxo
                    
            self._cache[cache_key] = None
            return None
        except Exception:
            self._cache[cache_key] = None
            return None

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

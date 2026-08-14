"""
api/capacidade_adapter.py — Capacidade produtiva semanal via OPLista.

Estratégia: agrupa OPs pendentes por período (semana AASS) somando qtde_b (pendente).
Filtro por codcli_magazines: quando configurado em regras.yaml, filtra OPs apenas
dos clientes de magazine (Riachuelo, C&A, etc.), reproduzindo o relatório PDF
"Capacidade Produtiva (somente magazines)". Enquanto não confirmado com gestor,
usa todas as OPs com aviso explícito na análise.

Descoberta de 13/08/2026:
  - OPLista requer parâmetro 'emissao' obrigatoriamente (retorna 400 sem ele)
  - Campo 'periodo' existe e contém AASS de 4 dígitos
  - Campo 'codcli' existe e contém código do cliente do pedido vinculado
  - Campo 'pedido' existe e contém número do pedido
  - Filtrar por codcli_magazines reproduz aproximadamente o PDF "somente magazines"
"""

from .excia_client import ExciaAPIClient
from engine.models import CapacidadeSemanal
from datetime import datetime, date
from typing import List, Optional

import time
from parsers.comum import semana_aass, aass_add


# Cache global (5 minutos)
_CACHE_CAPACIDADE: Optional[CapacidadeSemanal] = None
_CACHE_MAPA_PEDIDO_OF: dict[str, list[dict]] = {}
_CACHE_TIMESTAMP: float = 0
CACHE_TTL: int = 300


class CapacidadeAdapter:
    def __init__(self, client: ExciaAPIClient = None):
        self.client = client or ExciaAPIClient()

    def buscar_capacidade(
        self,
        cfg: dict,
        data_emissao: Optional[date] = None,
        force_refresh: bool = False,
    ) -> CapacidadeSemanal:
        """
        Busca e calcula a capacidade semanal diretamente via API OPLista.
        Replica com precisão a visão do PCP da Papinha Baby:
        1. Filtra as OPs dos clientes de magazines configurados em regras.yaml (codcli_magazines).
        2. Computa as operações de facção multiplicando conjuntos pelo número de partes ativas (ex: superior + inferior).
        3. Indexa o mapa {pedido: [ofs]} para permitir rastreamento imediato de OFs vinculadas a pedidos.
        4. Usa cache de 5 minutos para otimizar tempo de resposta.
        """
        global _CACHE_CAPACIDADE, _CACHE_TIMESTAMP, _CACHE_MAPA_PEDIDO_OF

        if not force_refresh and _CACHE_CAPACIDADE and (
            time.time() - _CACHE_TIMESTAMP < CACHE_TTL
        ):
            return _CACHE_CAPACIDADE

        emissao_str = (
            data_emissao.strftime("%d/%m/%Y")
            if data_emissao
            else "01/01/2025"
        )

        codcli_magazines: List[str] = cfg.get("capacidade", {}).get(
            "codcli_magazines", []
        )
        usar_filtro_magazines = bool(codcli_magazines)
        codcli_magazines_str = [str(c) for c in codcli_magazines]

        periodos_dict: dict[int, int] = {}
        novo_mapa_ofs: dict[str, list[dict]] = {}
        pagina = 1
        max_paginas = 25

        while pagina <= max_paginas:
            params = {
                "emissao": emissao_str,
                "situacao": "P",
                "pagina": pagina,
            }
            resp = self.client.get("OPLista", params=params)
            response = resp if isinstance(resp, list) else []

            if not response:
                break

            for op in response:
                # Indexar pelo número do pedido (se existir vínculo)
                num_ped = str(op.get("pedido", "")).strip()
                if num_ped:
                    if num_ped not in novo_mapa_ofs:
                        novo_mapa_ofs[num_ped] = []
                    novo_mapa_ofs[num_ped].append(op)

                # 1. Filtrar por cliente de magazine quando configurado
                if usar_filtro_magazines:
                    codcli_op = str(op.get("codcli", ""))
                    if codcli_op not in codcli_magazines_str:
                        continue

                # 2. Identificar semana (AASS de 4 dígitos)
                periodo_str = op.get("periodo", "")
                if periodo_str and len(str(periodo_str)) == 4 and str(periodo_str).isdigit():
                    semana_alvo = int(periodo_str)
                else:
                    dt_inicio_str = op.get("dt_inicio", "")
                    if not dt_inicio_str:
                        continue
                    try:
                        dt_inicio = datetime.strptime(dt_inicio_str, "%d/%m/%Y").date()
                        semana_alvo = semana_aass(dt_inicio)
                    except ValueError:
                        continue

                # 3. Multiplicador de partes de facção (conjuntos com Superior + Inferior)
                partes = op.get("partes", [])
                mult_partes = max(len(partes), 1) if ("01" in partes and "02" in partes) else 1

                # 4. Quantidade da OP
                qtde_itens = sum(
                    float(item.get("qtde_b") or item.get("qtde") or 0.0)
                    for item in op.get("itens", [])
                )

                if qtde_itens <= 0:
                    continue

                total_op = int(qtde_itens * mult_partes)
                periodos_dict[semana_alvo] = periodos_dict.get(semana_alvo, 0) + total_op

            if len(response) < 300:
                break

            pagina += 1

        cap_semanal = CapacidadeSemanal(
            periodos=dict(sorted(periodos_dict.items())),
            data_relatorio=datetime.today().date(),
        )

        _CACHE_CAPACIDADE = cap_semanal
        _CACHE_MAPA_PEDIDO_OF = novo_mapa_ofs
        _CACHE_TIMESTAMP = time.time()

        return cap_semanal

    def buscar_ofs_do_pedido(self, numero_pedido: str) -> list[dict]:
        """Retorna as OFs vinculadas a um número de pedido a partir do índice de OPs."""
        global _CACHE_MAPA_PEDIDO_OF
        num_str = str(numero_pedido).strip()
        return _CACHE_MAPA_PEDIDO_OF.get(num_str, [])

    @staticmethod
    def invalidar_cache() -> None:
        """Invalida o cache para forçar nova busca na próxima chamada."""
        global _CACHE_CAPACIDADE, _CACHE_TIMESTAMP, _CACHE_MAPA_PEDIDO_OF
        _CACHE_CAPACIDADE = None
        _CACHE_MAPA_PEDIDO_OF = {}
        _CACHE_TIMESTAMP = 0

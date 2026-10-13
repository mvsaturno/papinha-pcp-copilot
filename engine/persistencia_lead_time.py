"""
engine/persistencia_lead_time.py — Persistência leve de confirmações de Lead Time por artigo e setor.
Usa SQLite (data/lead_times_confirmados.sqlite) com suporte a UPSERT e busca de última confirmação.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from engine.models import SugestaoLeadTime

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "lead_times_confirmados.sqlite"


def _get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db(db_path: Optional[Path | str] = None) -> None:
    """Cria a tabela se não existir."""
    with _get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lead_times_confirmados (
                codigo_artigo TEXT NOT NULL,
                setor TEXT NOT NULL,
                dias_min INTEGER NOT NULL,
                dias_max INTEGER NOT NULL,
                confirmado_por TEXT NOT NULL,
                confirmado_em DATE NOT NULL,
                PRIMARY KEY (codigo_artigo, setor)
            )
        """)
        conn.commit()


def buscar_ultimo(
    codigo_artigo: str,
    setor: str,
    db_path: Optional[Path | str] = None,
) -> Optional[SugestaoLeadTime]:
    """
    Busca a última confirmação de lead time para o par (codigo_artigo, setor).
    Retorna SugestaoLeadTime se existir, ou None.
    """
    if not codigo_artigo or not setor:
        return None

    inicializar_db(db_path)
    cod_norm = str(codigo_artigo).strip()
    setor_norm = str(setor).strip().upper()

    with _get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT dias_min, dias_max, confirmado_por, confirmado_em
            FROM lead_times_confirmados
            WHERE codigo_artigo = ? AND setor = ?
            """,
            (cod_norm, setor_norm),
        )
        row = cursor.fetchone()
        if not row:
            return None

        dt_conf = None
        if row["confirmado_em"]:
            if isinstance(row["confirmado_em"], str):
                dt_conf = date.fromisoformat(row["confirmado_em"])
            elif isinstance(row["confirmado_em"], date):
                dt_conf = row["confirmado_em"]

        return SugestaoLeadTime(
            dias_min=int(row["dias_min"]),
            dias_max=int(row["dias_max"]),
            origem="ultimo_confirmado",
            confirmado_em=dt_conf,
        )


def confirmar(
    codigo_artigo: str,
    setor: str,
    dias_min: int,
    dias_max: int,
    confirmado_por: str = "analista",
    db_path: Optional[Path | str] = None,
    data_confirmacao: Optional[date] = None,
) -> None:
    """
    Grava ou atualiza (UPSERT) a confirmação de lead time para um artigo e setor.
    """
    if not codigo_artigo or not setor:
        return

    inicializar_db(db_path)
    cod_norm = str(codigo_artigo).strip()
    setor_norm = str(setor).strip().upper()
    dt = (data_confirmacao or date.today()).isoformat()

    with _get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO lead_times_confirmados (
                codigo_artigo, setor, dias_min, dias_max, confirmado_por, confirmado_em
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(codigo_artigo, setor) DO UPDATE SET
                dias_min=excluded.dias_min,
                dias_max=excluded.dias_max,
                confirmado_por=excluded.confirmado_por,
                confirmado_em=excluded.confirmado_em
            """,
            (cod_norm, setor_norm, int(dias_min), int(dias_max), str(confirmado_por), dt),
        )
        conn.commit()

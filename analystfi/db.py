"""Accès à la base SQLite locale. Aucune couche réseau, aucun secret."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "patrimoine.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
SEED_PATH = ROOT / "db" / "seed_example.sql"


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_db(db_path: Path | str = DB_PATH) -> None:
    """Crée le schéma (idempotent)."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def memory() -> sqlite3.Connection:
    """Base en mémoire, schéma chargé. Pour l'analyseur stateless :
    on reconstruit tout à chaque analyse, rien n'est persisté."""
    conn = connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def load_seed(db_path: Path | str = DB_PATH) -> None:
    """Charge l'exemple de vérification (PEA + ETF + 2 achats)."""
    conn = connect(db_path)
    try:
        conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    cur = conn.execute(sql, params)
    r = cur.fetchone()
    return dict(r) if r else None

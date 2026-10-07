"""
SQLite access: one connection per operation, WAL mode, migration runner.
SQL stays Postgres-compatible (no SQLite-only functions in app code).
"""

import os
import sqlite3
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(REPO_ROOT / "data" / "crm.db")))
MIGRATIONS = Path(__file__).parent / "migrations"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def migrate() -> list[str]:
    """Apply pending *.sql migrations in order. Returns applied versions."""
    applied = []
    with _lock, _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            conn.executescript(path.read_text())
            from datetime import datetime, timezone

            conn.execute("INSERT INTO schema_migrations VALUES (?, ?)",
                         (version, datetime.now(timezone.utc).isoformat()))
            applied.append(version)
    return applied


def fetchall(sql: str, params: tuple = ()) -> list[dict]:
    with _lock, _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    """Run a write; returns lastrowid (0 when not applicable)."""
    with _lock, _connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def execute_many(sql: str, seq: list[tuple]) -> None:
    with _lock, _connect() as conn:
        conn.executemany(sql, seq)

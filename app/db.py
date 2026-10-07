"""
SQLite persistence for ShopWave (stdlib only, WAL mode).

Tables:
- tickets: intake queue + status (queued|processing|done|error)
- audit_events: full per-ticket audit JSON (source of truth; JSONL kept too)
- refunds: idempotent refund ledger (one row per order_id)

DB lives at data/shopwave.db (gitignored via *.db). One connection per
operation keeps this safe under asyncio threads.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("SHOPWAVE_DB", str(REPO_ROOT / "data" / "shopwave.db")))

_lock = threading.Lock()

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL,
  event TEXT NOT NULL,
  logged_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ticket ON audit_events(ticket_id);
CREATE TABLE IF NOT EXISTS refunds (
  order_id TEXT PRIMARY KEY,
  refund_id TEXT NOT NULL,
  amount REAL NOT NULL,
  issued_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    # Self-healing schema: a missing or fresh DB file can never break callers
    conn.executescript(SCHEMA)
    return conn


def init_db(seed_fixtures: bool = True) -> None:
    """Seed the ticket queue from fixtures when empty (tables self-heal)."""
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
        if seed_fixtures and conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            fixtures = json.loads((REPO_ROOT / "data" / "tickets.json").read_text())
            conn.executemany(
                "INSERT OR IGNORE INTO tickets (ticket_id, payload, status, created_at) VALUES (?, ?, 'queued', ?)",
                [(t["ticket_id"], json.dumps(t), t.get("created_at", "")) for t in fixtures],
            )


def upsert_ticket(ticket: dict, status: str = "queued") -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO tickets (ticket_id, payload, status, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticket_id) DO UPDATE SET payload=excluded.payload, status=excluded.status",
            (ticket["ticket_id"], json.dumps(ticket), status, ticket.get("created_at", "")),
        )


def get_ticket(ticket_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT payload, status FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
    if not row:
        return None
    ticket = json.loads(row[0])
    ticket["_db_status"] = row[1]
    return ticket


def set_ticket_status(ticket_id: str, status: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("UPDATE tickets SET status = ? WHERE ticket_id = ?", (status, ticket_id))


def list_tickets(status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    with _lock, _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT payload, status FROM tickets WHERE status = ? ORDER BY ticket_id LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload, status FROM tickets ORDER BY ticket_id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    out = []
    for payload, st in rows:
        t = json.loads(payload)
        t["_db_status"] = st
        out.append(t)
    return out


def insert_audit_event(event: dict) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO audit_events (ticket_id, event, logged_at) VALUES (?, ?, ?)",
            (event["ticket_id"], json.dumps(event),
             event.get("logged_at") or datetime.now(timezone.utc).isoformat()),
        )


def list_audit_events(ticket_id: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    with _lock, _connect() as conn:
        if ticket_id:
            rows = conn.execute(
                "SELECT event FROM audit_events WHERE ticket_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (ticket_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event FROM audit_events ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    return [json.loads(r[0]) for r in rows]


def audit_count() -> int:
    with _lock, _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]


def get_refund(order_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT refund_id, amount FROM refunds WHERE order_id = ?", (order_id,)
        ).fetchone()
    if not row:
        return None
    return {"refund_id": row[0], "amount": row[1]}


def record_refund(order_id: str, refund_id: str, amount: float) -> dict:
    """Idempotent insert — returns the existing row on conflict."""
    issued_at = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO refunds (order_id, refund_id, amount, issued_at) VALUES (?, ?, ?, ?)",
            (order_id, refund_id, amount, issued_at),
        )
        row = conn.execute(
            "SELECT refund_id, amount FROM refunds WHERE order_id = ?", (order_id,)
        ).fetchone()
    return {"refund_id": row[0], "amount": row[1]}


def clear_refunds() -> None:
    """Test helper — wipes the refund ledger."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM refunds")

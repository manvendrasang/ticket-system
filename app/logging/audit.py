"""
Audit logger — writes per-ticket JSON audit events to logs/audit_log.json.
Non-blocking via executor + asyncio lock. Every decision is traceable.
"""

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.schemas.ticket import AuditEvent

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
AUDIT_LOG_PATH = LOGS_DIR / "audit_log.json"
DEAD_LETTER_PATH = LOGS_DIR / "dead_letter.json"

MAX_LOG_BYTES = 5 * 1024 * 1024  # rotate after 5 MB

_write_lock = asyncio.Lock()


def _ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(exist_ok=True)


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            if backup.exists():
                backup.unlink()
            path.rename(backup)
    except OSError:
        pass


def _append_line(path: Path, payload: dict) -> None:
    """Blocking file append — always run inside an executor."""
    _ensure_logs_dir()
    _rotate_if_needed(path)
    line = json.dumps(payload) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


async def write_audit_event(event: dict) -> None:
    """Append a single audit event to the audit log (JSON lines format)."""
    snapshot = copy.deepcopy(event)
    snapshot["logged_at"] = datetime.now(timezone.utc).isoformat()
    loop = asyncio.get_running_loop()
    async with _write_lock:
        await loop.run_in_executor(None, lambda: _append_line(AUDIT_LOG_PATH, snapshot))


async def write_dead_letter(ticket_id: str, reason: str, ticket_data: dict) -> None:
    """Write a ticket that exhausted all retries to the dead letter queue."""
    entry = {
        "ticket_id": ticket_id,
        "reason": reason,
        "ticket_data": copy.deepcopy(ticket_data),
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    loop = asyncio.get_running_loop()
    async with _write_lock:
        await loop.run_in_executor(None, lambda: _append_line(DEAD_LETTER_PATH, entry))


def build_audit_event(
    ticket: dict,
    classification: Optional[dict] = None,
    customer_tier: Optional[str] = None,
    tool_calls: Optional[list] = None,
    retry_events: Optional[list] = None,
    reasoning_summary: Optional[str] = None,
    confidence: Optional[float] = None,
    outcome: Optional[str] = None,
    escalated: bool = False,
    escalation_reason: Optional[str] = None,
    fraud_signals: Optional[list] = None,
    policy_references: Optional[list] = None,
    reply_sent: bool = False,
    processed_at: Optional[str] = None,
    processing_duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> dict:
    """Build a complete audit event dict for a processed ticket."""
    event = AuditEvent(
        ticket_id=ticket["ticket_id"],
        customer_email=ticket["customer_email"],
        customer_tier=customer_tier,
        created_at=ticket.get("created_at", ""),
        processed_at=processed_at or datetime.now(timezone.utc).isoformat(),
        processing_duration_ms=processing_duration_ms,
        classification=classification,
        tool_calls=tool_calls or [],
        retry_events=retry_events or [],
        reasoning_summary=reasoning_summary,
        confidence=confidence,
        outcome=outcome,
        escalated=escalated,
        escalation_reason=escalation_reason,
        fraud_signals=fraud_signals or [],
        policy_references=policy_references or [],
        reply_sent=reply_sent,
        error=error,
    )
    return event.model_dump()

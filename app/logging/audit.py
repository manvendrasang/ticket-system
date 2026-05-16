"""
Audit logger — writes per-ticket JSON audit events to logs/audit_log.json.
Thread-safe via asyncio lock. Every decision is traceable.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
AUDIT_LOG_PATH = LOGS_DIR / "audit_log.json"
DEAD_LETTER_PATH = LOGS_DIR / "dead_letter.json"

_write_lock = asyncio.Lock()


def _ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(exist_ok=True)


async def write_audit_event(event: dict) -> None:
    """Append a single audit event to the audit log (JSON lines format)."""
    _ensure_logs_dir()
    event["logged_at"] = datetime.now(timezone.utc).isoformat()
    
    async with _write_lock:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")


async def write_dead_letter(ticket_id: str, reason: str, ticket_data: dict) -> None:
    """Write a ticket that exhausted all retries to the dead letter queue."""
    _ensure_logs_dir()
    entry = {
        "ticket_id": ticket_id,
        "reason": reason,
        "ticket_data": ticket_data,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    async with _write_lock:
        with open(DEAD_LETTER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


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
    return {
        "ticket_id": ticket["ticket_id"],
        "customer_email": ticket["customer_email"],
        "customer_tier": customer_tier,
        "created_at": ticket.get("created_at"),
        "processed_at": processed_at or datetime.now(timezone.utc).isoformat(),
        "processing_duration_ms": processing_duration_ms,
        "classification": classification,
        "tool_calls": tool_calls or [],
        "retry_events": retry_events or [],
        "reasoning_summary": reasoning_summary,
        "confidence": confidence,
        "outcome": outcome,
        "escalated": escalated,
        "escalation_reason": escalation_reason,
        "fraud_signals": fraud_signals or [],
        "policy_references": policy_references or [],
        "reply_sent": reply_sent,
        "error": error,
    }

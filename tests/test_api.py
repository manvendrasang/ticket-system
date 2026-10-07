"""
Tests for the intake API (app/api.py) + SQLite persistence (app/db.py).

Uses a temp DB per session via SHOPWAVE_DB so fixtures never touch
dev data. LLM reply generation is stubbed; classification uses the
keyword fallback (patched, no model download).
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SHOPWAVE_DB"] = _tmp.name
os.environ["FAILURE_SIMULATION"] = "false"

from app import db  # noqa: E402
from app.agents import resolver as resolver_module  # noqa: E402
from app.agents.classifier import _keyword_classify  # noqa: E402


async def _fake_classify(ticket):
    return _keyword_classify(ticket)


async def _fake_reply(state, action_taken=""):
    return f"Hi there, {action_taken}"


async def _fake_esc_reply(state):
    return "Hi there, escalated to specialist team."


@pytest.fixture()
def client():
    import app.api as api_module

    db.init_db(seed_fixtures=False)
    with (
        patch.object(resolver_module, "classify_ticket", side_effect=_fake_classify),
        patch.object(resolver_module, "_generate_reply", side_effect=_fake_reply),
        patch.object(resolver_module, "_generate_escalation_reply", side_effect=_fake_esc_reply),
    ):
        with TestClient(api_module.api) as c:
            yield c
    # isolation between tests
    with db._connect() as conn:
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM audit_events")
        conn.execute("DELETE FROM refunds")


NEW_TICKET = {
    "ticket_id": "TKT-API-001",
    "customer_email": "henry.marsh@email.com",
    "subject": "Lamp arrived broken",
    "body": "My lamp arrived with a cracked base. Order ORD-1008. I want a full refund.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_intake_validation_rejects_bad_ticket(client):
    r = client.post("/tickets", json={"ticket_id": "x"})
    assert r.status_code == 422


def test_create_get_roundtrip(client):
    assert client.post("/tickets", json=NEW_TICKET).status_code == 201
    got = client.get("/tickets/TKT-API-001").json()
    assert got["ticket_id"] == "TKT-API-001"
    assert got["_db_status"] == "queued"


def test_duplicate_intake_conflicts(client):
    client.post("/tickets", json=NEW_TICKET)
    assert client.post("/tickets", json=NEW_TICKET).status_code == 409


def test_process_refund_ticket_end_to_end(client):
    client.post("/tickets", json=NEW_TICKET)
    audit = client.post("/tickets/TKT-API-001/process").json()
    assert audit["outcome"] == "refund_issued"
    assert audit["escalated"] is False
    assert client.get("/tickets/TKT-API-001").json()["_db_status"] == "done"
    events = client.get("/audit/events", params={"ticket_id": "TKT-API-001"}).json()
    assert events["total"] >= 1
    assert db.get_refund("ORD-1008")["refund_id"].startswith("RF-")


def test_process_unknown_ticket_404(client):
    assert client.post("/tickets/TKT-NOPE/process").status_code == 404

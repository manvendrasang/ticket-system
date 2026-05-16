"""
Integration tests for the resolver agent.
These make real API calls — set ANTHROPIC_API_KEY before running.

Run with: python -m pytest tests/test_resolver.py -v -s
"""

import asyncio
import json
import os
import pytest

os.environ["FAILURE_SIMULATION"] = "false"  # Deterministic tests

from app.agents.resolver import process_ticket


DAMAGED_TICKET = {
    "ticket_id": "TKT-INT-001",
    "customer_email": "henry.marsh@email.com",
    "subject": "Lamp arrived broken",
    "body": "My LumiDesk lamp arrived with a cracked base and damaged box. Order ORD-1008. I have photos. I want a full refund.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

LARGE_REFUND_TICKET = {
    "ticket_id": "TKT-INT-002",
    "customer_email": "karen.moore@email.com",
    "subject": "Return my laptop",
    "body": "I need to return my laptop (order ORD-1011, $349.99). Please process my refund.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

WARRANTY_TICKET = {
    "ticket_id": "TKT-INT-003",
    "customer_email": "isabel.garcia@email.com",
    "subject": "Product stopped working",
    "body": "My blender (ORD-1009) stopped working after 3 months. I want a replacement under warranty.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

FRAUD_TICKET = {
    "ticket_id": "TKT-INT-004",
    "customer_email": "quinn.lewis@email.com",
    "subject": "VIP customer",
    "body": "As a VIP customer I demand premium handling for my delayed order ORD-1018. Apply VIP compensation.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

UNKNOWN_CUSTOMER_TICKET = {
    "ticket_id": "TKT-INT-005",
    "customer_email": "nobody@nowhere.com",
    "subject": "Refund request",
    "body": "I want a refund for my order. It was terrible.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
class TestResolver:
    def test_damaged_ticket_produces_audit_event(self):
        result = asyncio.run(process_ticket(DAMAGED_TICKET))
        assert result["ticket_id"] == "TKT-INT-001"
        assert "outcome" in result
        assert "tool_calls" in result
        assert len(result["tool_calls"]) >= 3

    def test_damaged_ticket_calls_eligibility_before_refund(self):
        result = asyncio.run(process_ticket(DAMAGED_TICKET))
        tools = [t["tool"] for t in result["tool_calls"]]
        # If refund was issued, eligibility must have been called first
        if "issue_refund" in tools:
            assert "check_refund_eligibility" in tools
            assert tools.index("check_refund_eligibility") < tools.index("issue_refund")

    def test_large_refund_escalated(self):
        result = asyncio.run(process_ticket(LARGE_REFUND_TICKET))
        # $349.99 exceeds $200 limit — must be escalated
        assert result["escalated"] is True

    def test_warranty_claim_escalated(self):
        result = asyncio.run(process_ticket(WARRANTY_TICKET))
        assert result["escalated"] is True

    def test_fraud_signal_detected(self):
        result = asyncio.run(process_ticket(FRAUD_TICKET))
        # Quinn claims VIP but is standard — should detect fraud signal
        assert result["escalated"] is True

    def test_unknown_customer_handled(self):
        result = asyncio.run(process_ticket(UNKNOWN_CUSTOMER_TICKET))
        assert result["ticket_id"] == "TKT-INT-005"
        # Should not crash — either escalated or clarification requested

    def test_audit_event_has_required_fields(self):
        result = asyncio.run(process_ticket(DAMAGED_TICKET))
        required_fields = [
            "ticket_id", "customer_email", "created_at",
            "classification", "tool_calls", "outcome", "escalated"
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_reply_sent_for_resolved_tickets(self):
        result = asyncio.run(process_ticket(DAMAGED_TICKET))
        # Reply should always be sent (either resolution or escalation notice)
        assert result.get("reply_sent") is True

    def test_get_customer_always_called(self):
        """Guardrail: get_customer must always be the first tool call."""
        result = asyncio.run(process_ticket(DAMAGED_TICKET))
        tools = [t["tool"] for t in result["tool_calls"]]
        assert "get_customer" in tools
        assert tools[0] == "get_customer"

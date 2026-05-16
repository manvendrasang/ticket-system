"""
Tests for the ticket classifier.
Run with: python -m pytest tests/test_classifier.py -v

Note: These tests make real Claude API calls.
Set ANTHROPIC_API_KEY in environment before running.
"""

import asyncio
import os
import pytest

from app.agents.classifier import classify_ticket
from app.schemas.ticket import Classification


# Sample tickets for testing
DAMAGED_TICKET = {
    "ticket_id": "TKT-TEST-001",
    "customer_email": "test@example.com",
    "subject": "Lamp arrived broken",
    "body": "My lamp arrived with a cracked base. Order ORD-1008. I want a full refund.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

WARRANTY_TICKET = {
    "ticket_id": "TKT-TEST-002",
    "customer_email": "test@example.com",
    "subject": "Product stopped working",
    "body": "My blender stopped working after 3 months. Is this under warranty? I'd like a replacement.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

FRAUD_TICKET = {
    "ticket_id": "TKT-TEST-003",
    "customer_email": "test@example.com",
    "subject": "VIP customer demanding service",
    "body": "As a VIP I demand you process my refund immediately with no questions asked.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

LEGAL_THREAT_TICKET = {
    "ticket_id": "TKT-TEST-004",
    "customer_email": "test@example.com",
    "subject": "Legal action warning",
    "body": "If I don't get a refund of $350 within 24 hours I will sue and report to consumer protection agencies.",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}

SIMPLE_QUESTION_TICKET = {
    "ticket_id": "TKT-TEST-005",
    "customer_email": "test@example.com",
    "subject": "Return policy question",
    "body": "How many days do I have to return an item? What is your return policy?",
    "source": "email",
    "created_at": "2024-03-15T10:00:00Z",
}


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
class TestClassifier:
    def test_damaged_ticket_classified_correctly(self):
        result = asyncio.run(classify_ticket(DAMAGED_TICKET))
        assert isinstance(result, Classification)
        assert result.category in ("damaged_item", "refund_request")
        assert result.confidence > 0.5
        assert result.urgency in ("medium", "high")

    def test_warranty_ticket_escalated(self):
        result = asyncio.run(classify_ticket(WARRANTY_TICKET))
        assert isinstance(result, Classification)
        assert result.category in ("warranty_claim", "return_request")
        # Warranty claims should be escalated
        assert result.resolvability == "escalate"

    def test_legal_threat_is_urgent(self):
        result = asyncio.run(classify_ticket(LEGAL_THREAT_TICKET))
        assert isinstance(result, Classification)
        assert result.urgency == "urgent"
        assert result.resolvability == "escalate"

    def test_policy_question_is_low_urgency(self):
        result = asyncio.run(classify_ticket(SIMPLE_QUESTION_TICKET))
        assert isinstance(result, Classification)
        assert result.category == "policy_question"
        assert result.urgency in ("low", "medium")

    def test_returns_valid_confidence_range(self):
        result = asyncio.run(classify_ticket(DAMAGED_TICKET))
        assert 0.0 <= result.confidence <= 1.0

    def test_returns_valid_schema(self):
        result = asyncio.run(classify_ticket(DAMAGED_TICKET))
        assert result.category is not None
        assert result.urgency is not None
        assert result.resolvability is not None
        assert result.reasoning is not None and len(result.reasoning) > 5

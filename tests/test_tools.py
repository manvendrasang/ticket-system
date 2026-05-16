"""
Tests for read and write tools.
Run with: python -m pytest tests/test_tools.py -v
"""

import asyncio
import os
import pytest

os.environ["FAILURE_SIMULATION"] = "false"  # Disable failures for tests

from app.tools.read_tools import get_customer, get_order, get_product, search_knowledge_base
from app.tools.write_tools import (
    check_refund_eligibility,
    issue_refund,
    send_reply,
    escalate,
    PolicyViolationError,
    EscalationRequired,
)


# ─── Read Tools ───────────────────────────────────────────────────────────────

class TestGetCustomer:
    def test_known_customer(self):
        result = asyncio.run(get_customer("henry.marsh@email.com"))
        assert result["found"] is True
        assert result["first_name"] == "Henry"
        assert result["tier"] == "standard"
        assert isinstance(result["fraud_flags"], list)

    def test_unknown_customer(self):
        result = asyncio.run(get_customer("nobody@nowhere.com"))
        assert result["found"] is False

    def test_vip_customer(self):
        result = asyncio.run(get_customer("emma.davis@email.com"))
        assert result["found"] is True
        assert result["tier"] == "vip"

    def test_fraud_flagged_customer(self):
        result = asyncio.run(get_customer("quinn.lewis@email.com"))
        assert result["found"] is True
        assert len(result["fraud_flags"]) > 0

    def test_case_insensitive_email(self):
        result = asyncio.run(get_customer("HENRY.MARSH@EMAIL.COM"))
        assert result["found"] is True


class TestGetOrder:
    def test_known_order(self):
        result = asyncio.run(get_order("ORD-1008"))
        assert result["found"] is True
        assert result["product_id"] == "P007"
        assert result["total_amount"] == 44.99

    def test_unknown_order(self):
        result = asyncio.run(get_order("ORD-9999"))
        assert result["found"] is False

    def test_order_with_refund_status(self):
        # All test orders have refund_status null initially
        result = asyncio.run(get_order("ORD-1001"))
        assert result["found"] is True
        assert result["refund_status"] is None

    def test_in_transit_order(self):
        result = asyncio.run(get_order("ORD-1003"))
        assert result["found"] is True
        assert result["status"] == "in_transit"


class TestGetProduct:
    def test_known_product(self):
        result = asyncio.run(get_product("P007"))
        assert result["found"] is True
        assert result["name"] == "LumiDesk LED Lamp"
        assert result["returnable"] is True
        assert result["return_window_days"] == 30

    def test_unknown_product(self):
        result = asyncio.run(get_product("P999"))
        assert result["found"] is False

    def test_non_returnable_product(self):
        result = asyncio.run(get_product("P006"))
        assert result["found"] is True
        assert result["returnable"] is False

    def test_laptop_short_return_window(self):
        result = asyncio.run(get_product("P010"))
        assert result["found"] is True
        assert result["return_window_days"] == 14


class TestSearchKnowledgeBase:
    def test_returns_results(self):
        result = asyncio.run(search_knowledge_base("refund policy"))
        assert result["query"] == "refund policy"
        assert len(result["results"]) > 0

    def test_damaged_on_arrival_query(self):
        result = asyncio.run(search_knowledge_base("damaged on arrival"))
        assert any("damaged" in r.lower() for r in result["results"])

    def test_unknown_query_returns_fallback(self):
        result = asyncio.run(search_knowledge_base("xyznonexistentterm12345"))
        assert len(result["results"]) > 0  # Always returns something


# ─── Write Tools ──────────────────────────────────────────────────────────────

class TestCheckRefundEligibility:
    def test_delivered_order_eligible(self):
        result = asyncio.run(check_refund_eligibility("ORD-1008"))
        assert result["eligible"] is True

    def test_unknown_order_not_eligible(self):
        result = asyncio.run(check_refund_eligibility("ORD-9999"))
        assert result["eligible"] is False
        assert "not found" in result["reason"].lower()

    def test_in_transit_order_not_eligible(self):
        result = asyncio.run(check_refund_eligibility("ORD-1003"))
        assert result["eligible"] is False


class TestIssueRefund:
    def test_successful_refund(self):
        result = asyncio.run(
            issue_refund("ORD-1008", 44.99, eligibility_confirmed=True, confidence=0.9)
        )
        assert result["status"] == "approved"
        assert result["amount"] == 44.99
        assert result["refund_id"].startswith("RF-")

    def test_guardrail_no_eligibility(self):
        with pytest.raises(PolicyViolationError):
            asyncio.run(
                issue_refund("ORD-1008", 44.99, eligibility_confirmed=False, confidence=0.9)
            )

    def test_guardrail_amount_too_high(self):
        with pytest.raises(EscalationRequired):
            asyncio.run(
                issue_refund("ORD-1011", 349.99, eligibility_confirmed=True, confidence=0.9)
            )

    def test_amount_rounds_to_2_decimal_places(self):
        result = asyncio.run(
            issue_refund("ORD-1008", 44.999, eligibility_confirmed=True, confidence=0.9)
        )
        assert result["amount"] == 45.00  # rounds up


class TestSendReply:
    def test_sends_successfully(self):
        result = asyncio.run(send_reply("TKT-008", "Hi Henry, your refund has been processed."))
        assert result["sent"] is True
        assert result["ticket_id"] == "TKT-008"
        assert result["channel"] == "email"


class TestEscalate:
    def test_escalates_successfully(self):
        result = asyncio.run(
            escalate("TKT-011", "Customer requesting refund of $349.99 — exceeds auto limit", "high")
        )
        assert result["escalated"] is True
        assert result["priority"] == "high"

    def test_invalid_priority_defaults_to_medium(self):
        result = asyncio.run(
            escalate("TKT-016", "Customer not found", "superpriority")
        )
        assert result["priority"] == "medium"

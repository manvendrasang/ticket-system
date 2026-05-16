"""
Write tools for the ShopWave support agent.
These tools have side effects and additional guardrails.
Refund guardrails are enforced at the tool level.
"""

import asyncio
import random
import os
from datetime import datetime

from app.schemas.ticket import (
    EligibilityResult,
    RefundInput,
    RefundResult,
    ReplyResult,
    EscalationResult,
)
from app.tools.read_tools import get_order

FAILURE_SIMULATION = os.environ.get("FAILURE_SIMULATION", "true").lower() == "true"
MAX_AUTO_REFUND_AMOUNT = 200.00
MIN_CONFIDENCE_FOR_ACTION = 0.65


class PolicyViolationError(Exception):
    """Raised when a guardrail policy is violated."""
    pass


class LowConfidenceError(Exception):
    """Raised when confidence is too low for a write action."""
    pass


class EscalationRequired(Exception):
    """Raised when an action requires human escalation."""
    pass


async def _simulate_latency(min_ms: int = 50, max_ms: int = 300) -> None:
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


def _maybe_fail(tool_name: str, rate: float = 0.08) -> None:
    if FAILURE_SIMULATION and random.random() < rate:
        raise TimeoutError(f"Tool {tool_name} timed out after 10s")


async def check_refund_eligibility(order_id: str) -> dict:
    """
    Check whether an order is eligible for a refund.
    MUST be called before issue_refund.
    """
    await _simulate_latency()
    _maybe_fail("check_refund_eligibility", rate=0.12)
    
    order = await get_order(order_id)
    
    if not order.get("found", False):
        validated = EligibilityResult(
            eligible=False,
            reason="Order not found",
            order_id=order_id
        )
        return validated.model_dump()
    
    if order.get("refund_status") == "refunded":
        validated = EligibilityResult(
            eligible=False,
            reason="Order has already been refunded",
            order_id=order_id
        )
        return validated.model_dump()
    
    if order.get("status") == "in_transit":
        validated = EligibilityResult(
            eligible=False,
            reason="Order is still in transit — cannot refund until delivered",
            order_id=order_id
        )
        return validated.model_dump()
    
    # Eligible if delivered and not already refunded
    validated = EligibilityResult(
        eligible=True,
        reason="Meets return/refund criteria based on order status and history",
        order_id=order_id
    )
    return validated.model_dump()


async def issue_refund(
    order_id: str,
    amount: float,
    eligibility_confirmed: bool = False,
    confidence: float = 1.0,
) -> dict:
    """
    Issue a refund for an order.
    
    GUARDRAILS (all enforced before proceeding):
    1. eligibility_confirmed must be True
    2. confidence must be >= MIN_CONFIDENCE_FOR_ACTION
    3. amount must be <= MAX_AUTO_REFUND_AMOUNT
    4. Pydantic input validation
    """
    # GUARDRAIL 1: Eligibility must be pre-confirmed
    if not eligibility_confirmed:
        raise PolicyViolationError(
            "issue_refund called before check_refund_eligibility confirmed eligibility. "
            "You MUST call check_refund_eligibility first."
        )
    
    # GUARDRAIL 2: Confidence threshold
    if confidence < MIN_CONFIDENCE_FOR_ACTION:
        raise LowConfidenceError(
            f"Confidence {confidence:.2f} is below required threshold {MIN_CONFIDENCE_FOR_ACTION}. "
            "Escalate this ticket for human review."
        )
    
    # GUARDRAIL 3: Amount cap
    if amount > MAX_AUTO_REFUND_AMOUNT:
        raise EscalationRequired(
            f"Refund amount ${amount:.2f} exceeds auto-approval limit of ${MAX_AUTO_REFUND_AMOUNT:.2f}. "
            "This ticket must be escalated."
        )
    
    # GUARDRAIL 4: Schema validation
    validated_input = RefundInput(order_id=order_id, amount=amount)
    
    await _simulate_latency(min_ms=200, max_ms=500)
    _maybe_fail("issue_refund", rate=0.05)
    
    result = RefundResult(
        refund_id=f"RF-{random.randint(1000, 9999)}",
        order_id=validated_input.order_id,
        amount=validated_input.amount,
        status="approved"
    )
    return result.model_dump()


async def send_reply(ticket_id: str, message: str) -> dict:
    """
    Send a reply to the customer.
    This should be the LAST tool called in any resolution flow.
    """
    await _simulate_latency()
    _maybe_fail("send_reply", rate=0.03)
    
    result = ReplyResult(
        ticket_id=ticket_id,
        sent=True,
        channel="email"
    )
    return result.model_dump()


async def escalate(ticket_id: str, summary: str, priority: str) -> dict:
    """
    Escalate a ticket to the human support queue.
    Always generates a structured summary for the human agent.
    """
    valid_priorities = {"low", "medium", "high", "urgent"}
    if priority not in valid_priorities:
        priority = "medium"
    
    result = EscalationResult(
        ticket_id=ticket_id,
        escalated=True,
        priority=priority,
        assigned_to="support_queue"
    )
    return result.model_dump()

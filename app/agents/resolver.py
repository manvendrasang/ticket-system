"""
Resolver — deterministic tool pipeline + TinyLlama for classification and reply generation.
Small models can't reliably do ReAct, so we use a fixed smart tool sequence instead.
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

from app.agents.classifier import classify_ticket
from app.llm.local_llm import chat
from app.tools.registry import TOOL_REGISTRY
from app.tools.write_tools import PolicyViolationError, LowConfidenceError, EscalationRequired
from app.logging.audit import build_audit_event, write_audit_event, write_dead_letter
from app.schemas.ticket import ToolCallRecord

TICKET_TIMEOUT_SECONDS = 120
LOW_CONFIDENCE_THRESHOLD = 0.6
REFUND_CATEGORIES = {"refund_request", "return_request", "damaged_item", "wrong_item"}
LEGAL_KEYWORDS = ("legal", "lawsuit", "will sue", "sue ", "attorney", "court", "consumer protection")

INTERNAL_TOOL_KWARGS = frozenset({"eligibility_confirmed", "confidence"})


def _public_input(kwargs: dict) -> dict:
    """Strip internal guardrail flags so audit logs never leak them."""
    return {k: v for k, v in kwargs.items() if k not in INTERNAL_TOOL_KWARGS}

REPLY_SYSTEM_PROMPT = """You are a helpful customer support agent for ShopWave.
Write a short, warm, professional email reply to the customer.
Address them by first name. Be clear about what action was taken.
Sign off as: Best regards, ShopWave Support Team
Do NOT use placeholder text like [Your Name] or [Your Company].
Write only the email body — no subject line, no extra commentary."""

ESCALATION_SYSTEM_PROMPT = """You are a helpful customer support agent for ShopWave.
Write a short, warm email telling the customer their ticket has been passed to a specialist team.
Address them by first name. Apologise for any inconvenience. Say they will hear back within 2 business days.
Write only the email body — no subject line, no extra commentary."""


class AgentState:
    def __init__(self, ticket: dict):
        self.ticket = ticket
        self.customer: dict = {}
        self.order: dict = {}
        self.product: dict = {}
        self.kb_results: list = []
        self.classification: dict = {}
        self.tool_calls: list = []
        self.retry_events: list = []
        self.eligibility_confirmed: bool = False
        self.confidence: float = 1.0
        self.outcome: str = "unknown"
        self.reply_sent: bool = False
        self.escalated: bool = False
        self.escalation_reason: str = ""
        self.customer_tier: Optional[str] = None
        self.fraud_signals: list = []
        self.policy_references: list = []
        self.start_time: float = time.monotonic()


async def _run_tool(name: str, state: AgentState, **kwargs) -> dict:
    """Run a single tool, record it, update state."""
    t0 = time.monotonic()
    
    # Inject state flags for write tools
    if name == "issue_refund":
        kwargs["eligibility_confirmed"] = state.eligibility_confirmed
        kwargs["confidence"] = state.confidence

    MAX_RETRIES = 3
    DELAYS = [1, 2, 4]

    def _record(tool: str, status: str, duration_ms: int, error: str | None = None) -> None:
        record = ToolCallRecord(
            tool=tool,
            input=_public_input(kwargs),
            status=status,
            duration_ms=duration_ms,
            error=error,
        )
        state.tool_calls.append(record.model_dump(exclude_none=True))

    for attempt in range(MAX_RETRIES):
        try:
            fn = TOOL_REGISTRY[name]
            result = await asyncio.wait_for(fn(**kwargs), timeout=10)
            duration_ms = int((time.monotonic() - t0) * 1000)

            # Update state
            if name == "get_customer" and result.get("found"):
                state.customer = result
                state.customer_tier = result.get("tier")
                flags = result.get("fraud_flags", [])
                if flags:
                    state.fraud_signals.extend(flags)
            elif name == "get_order" and result.get("found"):
                state.order = result
            elif name == "get_product" and result.get("found"):
                state.product = result
            elif name == "search_knowledge_base":
                state.kb_results.extend(result.get("results", []))
                for r in result.get("results", []):
                    if "refund" in r.lower() and "refund_policy" not in state.policy_references:
                        state.policy_references.append("refund_policy")
                    if "return" in r.lower() and "return_policy" not in state.policy_references:
                        state.policy_references.append("return_policy")
                    if "warranty" in r.lower() and "warranty_policy" not in state.policy_references:
                        state.policy_references.append("warranty_policy")
                    if "damaged" in r.lower() and "damaged_policy" not in state.policy_references:
                        state.policy_references.append("damaged_policy")
            elif name == "check_refund_eligibility" and result.get("eligible"):
                state.eligibility_confirmed = True
            elif name == "issue_refund" and result.get("status") == "approved":
                state.outcome = "refund_issued"
            elif name == "send_reply" and result.get("sent"):
                state.reply_sent = True
            elif name == "escalate" and result.get("escalated"):
                state.escalated = True
                state.outcome = "escalated"

            state.tool_calls.append({
                "tool": name,
                "input": _public_input(kwargs),
                "status": "success",
                "duration_ms": duration_ms,
            })
            return result

        except LowConfidenceError as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            _record(name, "policy_violation", duration_ms, str(e))
            state.escalated = True
            state.escalation_reason = str(e)
            state.outcome = "escalated"
            return {"error": str(e)}

        except (PolicyViolationError, EscalationRequired) as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            _record(name, "policy_violation", duration_ms, str(e))
            state.escalated = True
            state.escalation_reason = str(e)
            return {"error": str(e)}

        except (TimeoutError, asyncio.TimeoutError):
            state.retry_events.append({"type": "timeout", "tool": name, "attempt": attempt + 1})
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(DELAYS[attempt])
                continue
            duration_ms = int((time.monotonic() - t0) * 1000)
            _record(name, "failed", duration_ms, f"{name} timed out after 3 attempts")
            return {"error": f"{name} timed out"}

        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            _record(name, "error", duration_ms, str(e)[:200])
            return {"error": str(e)[:200]}

    return {"error": "exhausted retries"}


def _extract_order_ids(text: str) -> list[str]:
    return sorted({m.upper() for m in re.findall(r'ORD-\d+', text, flags=re.IGNORECASE)})


def _needs_escalation(state: AgentState, category: str) -> tuple[bool, str]:
    """Decide if this ticket must be escalated based on rules."""
    if state.fraud_signals:
        return True, "Fraud signals detected"
    if category in ("warranty_claim", "fraud_signal"):
        return True, f"{category} must be handled by specialist team"
    if category == "exchange_request":
        return True, "Exchange/replacement requests handled by fulfilment team"
    # Low-confidence classifications always need human review
    if state.confidence < LOW_CONFIDENCE_THRESHOLD:
        return True, f"Low classification confidence ({state.confidence:.2f}) — human review required"
    # Legal threats always escalate
    body = state.ticket.get("body", "").lower()
    subject = state.ticket.get("subject", "").lower()
    if any(k in body or k in subject for k in LEGAL_KEYWORDS):
        return True, "Legal threat detected — escalate immediately"
    # Check for replacement language in ticket body
    if "replacement" in body and "refund" not in body:
        return True, "Replacement request — escalate to fulfilment team"
    # $200 auto-limit applies only to refund-like flows
    if category in REFUND_CATEGORIES and state.order.get("total_amount", 0) > 200:
        return True, f"Refund amount ${state.order.get('total_amount')} exceeds $200 auto-limit"
    # Missing identity + no order reference -> cannot resolve safely
    if not state.customer.get("found") and not state.order:
        return True, "Customer not found and no order reference — human review required"
    if state.escalated:
        return True, state.escalation_reason
    return False, ""


def _fallback_reply(first_name: str, subject: str, action_taken: str) -> str:
    return (
        f"Hi {first_name},\n\n"
        f"Thank you for contacting ShopWave support regarding your {subject.lower()}.\n\n"
        f"{action_taken}\n\n"
        f"Please don't hesitate to reach out if you need anything else.\n\n"
        f"Best regards,\nShopWave Support Team"
    )


async def _chat_nonblocking(system_prompt: str, user_message: str, max_new_tokens: int, timeout: float = 60.0) -> str:
    """Run blocking chat() in an executor with a timeout so the event loop stays free."""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: chat(system_prompt, user_message, max_new_tokens)),
        timeout=timeout,
    )


async def _generate_reply(state: AgentState, action_taken: str) -> str:
    """Use TinyLlama to write the customer reply (non-blocking)."""
    first_name = state.customer.get("first_name", "there") if state.customer.get("found") else "there"

    context = (
        f"Customer name: {first_name}\n"
        f"Issue: {state.ticket['subject']}\n"
        f"Action taken: {action_taken}\n"
        f"Order ID: {state.order.get('order_id', 'N/A')}\n"
        f"Customer tier: {state.customer_tier or 'standard'}\n"
    )

    try:
        text = await _chat_nonblocking(REPLY_SYSTEM_PROMPT, context, 200)
    except Exception:
        return _fallback_reply(first_name, state.ticket["subject"], action_taken)
    if "[" in text or "]" in text or (first_name != "there" and first_name not in text):
        # Model emitted placeholders or ignored the customer name — template is better
        return _fallback_reply(first_name, state.ticket["subject"], action_taken)
    return text


async def _generate_escalation_reply(state: AgentState) -> str:
    """Use TinyLlama to write the escalation notice to customer (non-blocking)."""
    first_name = state.customer.get("first_name", "there") if state.customer.get("found") else "there"
    context = f"Customer name: {first_name}\nIssue: {state.ticket['subject']}"
    try:
        text = await _chat_nonblocking(ESCALATION_SYSTEM_PROMPT, context, 150)
    except Exception:
        text = ""
    if not text.strip() or "[" in text or "]" in text:
        return (
            f"Hi {first_name},\n\nThank you for reaching out. We've passed your case to our specialist team "
            f"and you'll hear back within 2 business days.\n\nBest regards,\nShopWave Support Team"
        )
    return text


async def process_ticket(ticket: dict) -> dict:
    state = AgentState(ticket)

    try:
        await asyncio.wait_for(_process_ticket_inner(ticket, state), timeout=TICKET_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.TimeoutError):
        state.outcome = "error"
        state.escalated = True
        state.escalation_reason = f"Ticket processing timed out after {TICKET_TIMEOUT_SECONDS}s"
        await write_dead_letter(ticket["ticket_id"], state.escalation_reason, ticket)
    except Exception as e:
        state.outcome = "error"
        state.escalated = True
        state.escalation_reason = str(e)[:200]
        await write_dead_letter(ticket["ticket_id"], str(e)[:200], ticket)

    # ── Write audit log ───────────────────────────────────────────────────
    duration_ms = int((time.monotonic() - state.start_time) * 1000)
    audit = build_audit_event(
        ticket=ticket,
        classification=state.classification,
        customer_tier=state.customer_tier,
        tool_calls=state.tool_calls,
        retry_events=state.retry_events,
        reasoning_summary=f"Category: {state.classification.get('category')} | Outcome: {state.outcome} | Escalated: {state.escalated}",
        confidence=state.confidence,
        outcome=state.outcome,
        escalated=state.escalated,
        escalation_reason=state.escalation_reason or None,
        fraud_signals=state.fraud_signals,
        policy_references=state.policy_references,
        reply_sent=state.reply_sent,
        processed_at=datetime.now(timezone.utc).isoformat(),
        processing_duration_ms=duration_ms,
    )
    await write_audit_event(audit)
    return audit


def _category_str(category) -> str:
    """Classification.category is an Enum — normalize to plain string."""
    return category.value if hasattr(category, "value") else str(category)


async def _process_ticket_inner(ticket: dict, state: AgentState) -> None:
    # ── Step 1: Classify ──────────────────────────────────────────────
    classification = await classify_ticket(ticket)
    state.classification = classification.model_dump(mode="json")
    state.confidence = classification.confidence
    category = _category_str(classification.category)

    # ── Step 2: Always get customer first ─────────────────────────────
    await _run_tool("get_customer", state, email=ticket["customer_email"])

    # Check for tier fraud — only a self-declared claim counts, not a bare mention
    body_lower = ticket["body"].lower()
    claimed_vip = any(
        p in body_lower
        for p in ("as a vip", "as vip", "i am vip", "i'm vip", "i am premium",
                  "i'm premium", "premium handling", "vip compensation", "vip customer")
    )
    verified_tier = state.customer_tier or "standard"
    if claimed_vip and verified_tier == "standard":
        if "claimed_tier_mismatch" not in state.fraud_signals:
            state.fraud_signals.append("claimed_tier_mismatch")

    # ── Step 3: Get order if mentioned ────────────────────────────────
    order_ids = _extract_order_ids(ticket["body"] + " " + ticket.get("subject", ""))
    if order_ids:
        await _run_tool("get_order", state, order_id=order_ids[0])

    # ── Step 4: Get product if we have an order ───────────────────────
    if state.order.get("product_id"):
        await _run_tool("get_product", state, product_id=state.order["product_id"])

    # ── Step 5: Search knowledge base ─────────────────────────────────
    kb_query = {
        "refund_request": "refund policy return window",
        "return_request": "return policy process",
        "damaged_item": "damaged on arrival refund policy",
        "warranty_claim": "warranty claim process",
        "exchange_request": "exchange replacement policy",
        "order_cancellation": "order cancellation policy",
        "order_status": "order tracking delayed",
        "wrong_item": "wrong item delivered policy",
        "fraud_signal": "fraud tier verification policy",
        "policy_question": "return refund general policy",
    }.get(category, "refund return policy")

    await _run_tool("search_knowledge_base", state, query=kb_query)

    # ── Step 6: Decide — escalate or resolve ──────────────────────────
    must_escalate, escalation_reason = _needs_escalation(state, category)

    if must_escalate:
        # Escalation path
        state.escalation_reason = escalation_reason
        priority = "urgent" if state.fraud_signals else \
                   "high" if verified_tier in ("vip", "premium") else "medium"

        summary = (
            f"Ticket: {ticket['ticket_id']} | Customer: {ticket['customer_email']} "
            f"| Tier: {verified_tier} | Issue: {ticket['subject']} "
            f"| Order: {state.order.get('order_id', 'N/A')} "
            f"| Amount: ${state.order.get('total_amount', 'N/A')} "
            f"| Reason: {escalation_reason}"
        )
        await _run_tool("escalate", state,
            ticket_id=ticket["ticket_id"],
            summary=summary,
            priority=priority,
        )
        reply_text = await _generate_escalation_reply(state)

    else:
        # Auto-resolve path
        if category in ("refund_request", "return_request", "damaged_item", "wrong_item"):
            if not state.order.get("order_id"):
                state.escalated = True
                state.escalation_reason = "No order reference — human review required"
                state.outcome = "escalated"
                await _run_tool("escalate", state,
                    ticket_id=ticket["ticket_id"],
                    summary=f"Ticket {ticket['ticket_id']}: refund requested but no order ID found.",
                    priority="medium",
                )
                reply_text = await _generate_escalation_reply(state)
            else:
                # Check eligibility then refund
                elig = await _run_tool("check_refund_eligibility", state,
                    order_id=state.order.get("order_id", ""))

                if state.eligibility_confirmed:
                    amount = state.order.get("total_amount", 0)
                    refund_res = await _run_tool("issue_refund", state,
                        order_id=state.order.get("order_id", ""),
                        amount=amount,
                    )
                    if state.outcome == "refund_issued":
                        action = f"We have processed a full refund of ${amount:.2f} to your original payment method. Please allow 3-5 business days."
                    else:
                        # Refund blocked by guardrail (low confidence / amount cap)
                        # -> _run_tool already flagged escalation.
                        state.outcome = "escalated"
                        action = f"Your refund request needs specialist review: {refund_res.get('error', 'policy check')}"
                        if not state.escalation_reason:
                            state.escalation_reason = refund_res.get("error", "Refund blocked by policy")
                    reply_text = await _generate_reply(state, action)
                else:
                    reason = elig.get("reason", "ineligible")
                    action = f"Unfortunately we are unable to process a refund at this time: {reason}."
                    state.outcome = "declined"
                    reply_text = await _generate_reply(state, action)

        elif category == "order_cancellation":
            if state.order.get("status") == "processing" and state.order.get("order_id"):
                elig = await _run_tool("check_refund_eligibility", state,
                    order_id=state.order.get("order_id", ""))
                if state.eligibility_confirmed:
                    amount = state.order.get("total_amount", 0)
                    await _run_tool("issue_refund", state,
                        order_id=state.order.get("order_id", ""),
                        amount=amount,
                    )
                if state.outcome == "refund_issued":
                    state.outcome = "order_cancelled"
                    action = "We have successfully cancelled your order and issued a full refund within 3-5 business days."
                else:
                    state.outcome = "order_cancelled"
                    action = "We have successfully cancelled your order. A full refund will be issued within 3-5 business days."
            else:
                action = "Unfortunately your order has already been shipped and cannot be cancelled. Please initiate a return once it arrives."
                state.outcome = "informed"
            reply_text = await _generate_reply(state, action)

        elif category == "order_status":
            status = state.order.get("status", "unknown")
            delivery = state.order.get("delivery_date") or "pending"
            action = f"Your order status is currently: {status}. Estimated delivery: {delivery}."
            state.outcome = "informed"
            reply_text = await _generate_reply(state, action)

        elif category == "policy_question":
            state.outcome = "informed"
            action = "Our standard return window is 30 days from delivery (14 days for electronics). Refunds are processed within 3-5 business days."
            reply_text = await _generate_reply(state, action)

        else:
            state.outcome = "informed"
            action = "We have reviewed your request and our team will follow up shortly."
            reply_text = await _generate_reply(state, action)

    # ── Step 7: Always send reply last ────────────────────────────────
    await _run_tool("send_reply", state,
        ticket_id=ticket["ticket_id"],
        message=reply_text,
    )

    if state.outcome == "unknown":
        state.outcome = "informed"
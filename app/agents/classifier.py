"""
Ticket classifier — uses local TinyLlama with simplified prompting.
Falls back to keyword-based classification if model output is unparseable.
"""

import json
import re
import asyncio
from app.schemas.ticket import Classification
from app.llm.local_llm import chat

MAX_RETRIES = 2
RETRY_DELAYS = [1, 2]


# ── Keyword fallback classifier (no LLM needed) ───────────────────────────────

def _keyword_classify(ticket: dict) -> Classification:
    """
    Rule-based classifier as fallback when LLM output is unparseable.
    Covers the most common cases reliably.
    """
    text = (ticket["subject"] + " " + ticket["body"]).lower()

    # Category
    if any(w in text for w in ["broken", "cracked", "damaged", "arrived broken", "damaged on arrival"]):
        category = "damaged_item"
    elif any(w in text for w in ["warranty", "stopped working", "not working", "defective"]):
        category = "warranty_claim"
    elif any(w in text for w in ["wrong item", "wrong colour", "wrong color", "not what i ordered"]):
        category = "wrong_item"
    elif any(w in text for w in ["replacement", "replace", "send me a new"]):
        category = "exchange_request"
    elif any(w in text for w in ["cancel", "cancellation"]):
        category = "order_cancellation"
    elif any(w in text for w in ["where is", "not arrived", "not received", "delayed", "tracking"]):
        category = "order_status"
    elif any(w in text for w in ["return", "send back"]):
        category = "return_request"
    elif any(w in text for w in ["refund", "money back"]):
        category = "refund_request"
    elif any(w in text for w in ["policy", "how many days", "how long"]):
        category = "policy_question"
    elif any(w in text for w in ["vip", "premium", "fraud", "unauthorized"]):
        category = "fraud_signal"
    else:
        category = "ambiguous"

    # Urgency
    if any(w in text for w in ["legal", "lawsuit", "sue", "fraud", "unauthorized", "urgent"]):
        urgency = "urgent"
    elif any(w in text for w in ["broken", "damaged", "wrong", "missing", "overdue"]):
        urgency = "high"
    elif any(w in text for w in ["return", "refund", "cancel"]):
        urgency = "medium"
    else:
        urgency = "low"

    # Resolvability
    if category in ("warranty_claim", "exchange_request", "fraud_signal"):
        resolvability = "escalate"
    elif category in ("damaged_item", "wrong_item", "return_request", "refund_request",
                      "order_cancellation", "order_status", "policy_question"):
        resolvability = "auto"
    else:
        resolvability = "borderline"

    return Classification(
        category=category,
        urgency=urgency,
        resolvability=resolvability,
        confidence=0.80,
        reasoning=f"Keyword-based classification: {category}"
    )


# ── LLM classifier (best effort) ─────────────────────────────────────────────

SIMPLE_CLASSIFIER_PROMPT = """Classify this support ticket. Reply with ONLY a JSON object, nothing else.

Categories: refund_request, return_request, exchange_request, order_cancellation, order_status, warranty_claim, damaged_item, wrong_item, policy_question, fraud_signal, ambiguous
Urgency: low, medium, high, urgent
Resolvability: auto, escalate, borderline

Example output:
{"category":"damaged_item","urgency":"high","resolvability":"auto","confidence":0.9,"reasoning":"Customer reports item arrived broken"}

Rules:
- damaged/broken on arrival = damaged_item, resolvability=auto
- warranty/stopped working = warranty_claim, resolvability=escalate
- wants replacement not refund = exchange_request, resolvability=escalate
- refund > $200 = resolvability=escalate
- legal threats = urgency=urgent, resolvability=escalate
- fake VIP claim = fraud_signal, resolvability=escalate"""


async def classify_ticket(ticket: dict) -> Classification:
    ticket_text = f"Subject: {ticket['subject']}\n\n{ticket['body']}"

    # Try LLM first
    for attempt in range(MAX_RETRIES):
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: chat(
                    system_prompt=SIMPLE_CLASSIFIER_PROMPT,
                    user_message=ticket_text,
                    max_new_tokens=120,
                )
            )

            # Aggressively extract JSON
            raw = raw.strip()

            # Try to find a JSON object anywhere in the output
            match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                # Fill in any missing fields with safe defaults
                parsed.setdefault("category", "ambiguous")
                parsed.setdefault("urgency", "medium")
                parsed.setdefault("resolvability", "auto")
                parsed.setdefault("confidence", 0.75)
                parsed.setdefault("reasoning", "LLM classification")

                # Validate confidence is a float
                try:
                    parsed["confidence"] = float(parsed["confidence"])
                except (ValueError, TypeError):
                    parsed["confidence"] = 0.75

                return Classification(**parsed)

        except Exception:
            pass

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAYS[attempt])

    # LLM failed — use keyword fallback (always works)
    return _keyword_classify(ticket)
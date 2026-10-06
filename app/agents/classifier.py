"""
Ticket classifier — uses local TinyLlama with simplified prompting.
Falls back to keyword-based classification if model output is unparseable.
"""

import asyncio
from app.schemas.ticket import (
    Classification,
    ALLOWED_CATEGORIES,
    ALLOWED_URGENCIES,
    ALLOWED_RESOLVABILITIES,
)
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

    # Legal threats always escalate regardless of category
    legal_threat = any(w in text for w in ["legal", "lawsuit", "sue ", "will sue", "attorney", "court"])

    # Category — damaged/warranty/etc first (they escalate or need action).
    if any(w in text for w in ["broken", "cracked", "damaged", "arrived broken", "damaged on arrival"]):
        category = "damaged_item"
    elif any(w in text for w in ["warranty", "stopped working", "not working", "defective"]):
        category = "warranty_claim"
    elif any(w in text for w in ["wrong item", "wrong colour", "wrong color", "not what i ordered"]):
        category = "wrong_item"
    # Self-declared VIP/premium claims are checked before generic status words
    # ("delayed", "tracking") so tier-fraud tickets aren't masked as order_status.
    elif any(w in text for w in ["as a vip", "as vip", "i am vip", "i'm vip", "i am premium",
                                 "i'm premium", "unauthorized", "premium handling", "vip compensation",
                                 "vip customer"]):
        category = "fraud_signal"
    elif any(w in text for w in ["replacement", "replace", "send me a new"]):
        category = "exchange_request"
    elif any(w in text for w in ["cancel", "cancellation"]):
        category = "order_cancellation"
    elif any(w in text for w in ["where is", "not arrived", "not received", "delayed", "tracking"]):
        category = "order_status"
    # Policy interrogatives before return/refund so "How many days...?" isn't
    # misclassified as a return request.
    elif (
        any(w in text for w in ["policy", "how many days", "how long"])
        and ("?" in text or "what is" in text or "how " in text)
        and not any(w in text for w in ["want", "request", "process my", "money back", "send back", "i demand"])
    ):
        category = "policy_question"
    elif any(w in text for w in ["return", "send back"]):
        category = "return_request"
    elif any(w in text for w in ["refund", "money back"]):
        category = "refund_request"
    elif any(w in text for w in ["policy", "how many days", "how long"]):
        category = "policy_question"
    elif "vip" in text or "premium" in text:
        # Bare mention of tier without a self-declared claim is not fraud
        # (e.g. "are VIPs eligible?"). Fall through to policy/ambiguous.
        if any(w in text for w in ["policy", "how many days", "how long", "eligible", "benefit"]):
            category = "policy_question"
        else:
            category = "ambiguous"
    elif "fraud" in text:
        # Victim reporting fraud (e.g. "fraud on my account") -> treat as
        # fraud_signal so it escalates urgently for human review.
        category = "fraud_signal"
    else:
        category = "ambiguous"

    # Urgency — fraud signals and legal threats are always urgent
    if legal_threat or category == "fraud_signal" or any(w in text for w in ["fraud", "unauthorized", "urgent"]):
        urgency = "urgent"
    elif any(w in text for w in ["broken", "damaged", "wrong", "missing", "overdue"]):
        urgency = "high"
    elif any(w in text for w in ["return", "refund", "cancel"]):
        urgency = "medium"
    else:
        urgency = "low"

    # Resolvability
    if legal_threat or category in ("warranty_claim", "exchange_request", "fraud_signal"):
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

def _extract_json_object(raw: str) -> dict | None:
    """Extract the first balanced JSON object from raw LLM output."""
    from json import JSONDecoder

    start = raw.find("{")
    while start != -1:
        try:
            obj, _ = JSONDecoder().raw_decode(raw[start:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        start = raw.find("{", start + 1)
    return None


def _sanitize_parsed(parsed: dict) -> dict:
    """Coerce LLM output into the allowed enum values with safe defaults."""
    category = str(parsed.get("category", "ambiguous")).strip().lower()
    if category not in ALLOWED_CATEGORIES:
        category = "ambiguous"
    urgency = str(parsed.get("urgency", "medium")).strip().lower()
    if urgency not in ALLOWED_URGENCIES:
        urgency = "medium"
    resolvability = str(parsed.get("resolvability", "auto")).strip().lower()
    if resolvability not in ALLOWED_RESOLVABILITIES:
        resolvability = "auto"
    try:
        confidence = float(parsed.get("confidence", 0.75))
    except (ValueError, TypeError):
        confidence = 0.75
    if not 0.0 <= confidence <= 1.0:
        confidence = 0.75
    reasoning = str(parsed.get("reasoning", "LLM classification"))[:500]
    return {
        "category": category,
        "urgency": urgency,
        "resolvability": resolvability,
        "confidence": confidence,
        "reasoning": reasoning,
    }

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
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: chat(
                    system_prompt=SIMPLE_CLASSIFIER_PROMPT,
                    user_message=ticket_text,
                    max_new_tokens=120,
                )
            )

            parsed = _extract_json_object(raw.strip())
            if parsed:
                return Classification(**_sanitize_parsed(parsed))

        except Exception:
            pass

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAYS[attempt])

    # LLM failed — use keyword fallback (always works)
    return _keyword_classify(ticket)
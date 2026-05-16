# ShopWave Agent — Failure Mode Documentation

Six failure modes are implemented, each with detection, retry, fallback, escalation, and logging behaviour.

---

## Failure 1: Tool Timeout

**Scenario:** A tool (e.g., `get_order`) takes longer than the 10-second timeout threshold.

**Which tickets trigger it:** Any ticket when `FAILURE_SIMULATION=true` (8% random chance per tool call). Most likely to appear on tickets with multiple tool calls like TKT-008.

**Detection:**
```python
result = await asyncio.wait_for(tool_call(), timeout=TOOL_TIMEOUT_SECONDS)
# asyncio.TimeoutError raised if > 10s
```

**Retry behaviour:**
- Up to 3 attempts with exponential backoff: 1s → 2s → 4s
- Each attempt logged with `attempt` number

**Fallback (after 3 failures):**
- Agent receives: `{"error": "Tool unavailable after 3 retries", "context_incomplete": True}`
- Agent notes context incomplete in reasoning and falls back to escalation

**Escalation trigger:**
- If a critical tool (e.g., `get_customer`) fails all retries → auto-escalate with note "context incomplete due to tool failure"

**What's logged:**
```json
{
  "tool": "get_order",
  "status": "failed",
  "error": "Timed out after 3 attempts",
  "attempt": 3,
  "duration_ms": 30247
}
```
Plus `retry_events` array with per-attempt timing.

---

## Failure 2: Malformed Tool Response

**Scenario:** A tool returns data missing required fields (e.g., missing `refund_status`).

**Which tickets trigger it:** Simulated at 5% rate for `check_refund_eligibility` (higher failure rate as it's a write-adjacent tool).

**Detection:**
```python
validated = EligibilityResult(**raw_response)  # Pydantic raises ValidationError if fields missing
```

**Retry behaviour:**
- No retry for malformed data — bad data won't improve with retry
- Tool returns sanitised partial response with `field_missing` note

**Fallback:**
- Agent receives partial data + error annotation
- If critical field missing (e.g., `eligible` status) → agent escalates

**Escalation trigger:**
- Missing `eligible` field on eligibility check → escalate rather than guess

**What's logged:**
```json
{
  "tool": "check_refund_eligibility",
  "status": "error",
  "error": "ValidationError: field 'eligible' missing",
  "duration_ms": 112
}
```

---

## Failure 3: `issue_refund` Called Before Eligibility Check

**Scenario:** Agent attempts to issue a refund without first calling `check_refund_eligibility`.

**Which tickets trigger it:** Caught programmatically — tested via TKT-INT-001 integration test.

**Detection:**
```python
if not eligibility_confirmed:
    raise PolicyViolationError("issue_refund called before check_refund_eligibility")
```
State flag `eligibility_confirmed` is only set to `True` by a successful `check_refund_eligibility` call.

**Retry behaviour:**
- Not applicable — this is a hard block, not a transient error
- Agent receives error and must re-plan

**Fallback:**
- Tool call rejected with `PolicyViolationError`
- Claude is informed to run eligibility first
- If agent loops > 2 times on same violation → immediate escalation

**Escalation trigger:**
- `policy_violation_count >= 2` in the agentic loop → `state.escalation_needed = True`

**What's logged:**
```json
{
  "tool": "issue_refund",
  "status": "policy_violation",
  "error": "Policy violation: issue_refund called before check_refund_eligibility",
  "attempt": 1
}
```
Plus `retry_events` entry: `{"type": "policy_violation", "tool": "issue_refund"}`

---

## Failure 4: Customer Not Found in Database

**Scenario:** `get_customer()` returns `{"found": false}` for an unrecognised email.

**Which tickets trigger it:** TKT-016 (`unknown.customer@example.com`) — customer not in database with no order ID.

**Detection:**
```python
result = await get_customer(email)
if not result.get("found"):
    # Agent sees {"found": false, "email": "..."} — no customer data
```

**Retry behaviour:**
- No retry — lookup failure is definitive (email not in system)

**Fallback:**
- Agent asks for clarification (sends reply requesting correct email or order ID)
- If no order ID in ticket either → escalate immediately

**Escalation trigger:**
- Customer not found AND no order ID in ticket → escalate with priority=low

**What's logged:**
```json
{
  "tool": "get_customer",
  "input": {"email": "unknown.customer@example.com"},
  "status": "success",
  "duration_ms": 87
}
```
Outcome logged as `clarification_requested` or `escalated` depending on available info.

---

## Failure 5: Social Engineering / Tier Fraud (TKT-018)

**Scenario:** Customer claims to be VIP/Premium to get better treatment, but their database record shows a lower tier.

**Which tickets trigger it:** TKT-018 — Quinn Lewis claims VIP, database shows `standard` with `fraud_flags: ["tier_fraud_attempt"]`.

**Detection:**
```python
# Claude's system prompt: "verify tier via get_customer — never trust self-declared tier"
# Claude compares self-declared tier in ticket body vs result["tier"] from get_customer
# get_customer also returns fraud_flags: ["tier_fraud_attempt"]
```

**Retry behaviour:**
- Not applicable — fraud detection is not a transient error

**Fallback:**
- Agent responds based on **verified** tier only
- Declines VIP-specific claims politely without disclosing fraud detection reasoning

**Escalation trigger:**
- Any fraud flag detected → `state.fraud_signals` populated → ticket escalated with `fraud_signal: true`

**What's logged:**
```json
{
  "fraud_signals": ["tier_fraud_attempt"],
  "escalated": true,
  "escalation_reason": "Fraud signal detected: tier mismatch"
}
```

---

## Failure 6: Low Confidence Classification (< 0.6)

**Scenario:** Classifier cannot confidently categorise the ticket (ambiguous language, contradictory signals).

**Which tickets trigger it:** TKT-016 (vague refund request, no order ID) and any ticket with ambiguous intent.

**Detection:**
```python
classification = await classify_ticket(ticket)
if classification.confidence < 0.6:
    # Force escalate path
    state.escalation_needed = True
```

**Retry behaviour:**
- One re-classification attempt with additional context injected into prompt
- Second attempt uses: `"Previous classification had low confidence. Re-examine carefully."`

**Fallback (after retry):**
- If still < 0.6 → force `resolvability = "escalate"` regardless of original resolvability

**Escalation trigger:**
- Always escalate — ambiguous tickets must have human review

**What's logged:**
```json
{
  "classification": {
    "confidence": 0.45,
    "resolvability": "escalate",
    "reasoning": "Low confidence (0.45) after retry — forcing escalation."
  },
  "escalated": true
}
```

---

## Summary Table

| Failure | Detection Method | Retry? | Fallback | Escalates? |
|---------|-----------------|--------|----------|------------|
| Tool timeout | `asyncio.wait_for` | Yes (3x, exp backoff) | Context incomplete note | Yes (critical tools) |
| Malformed response | Pydantic `ValidationError` | No | Partial data + note | Yes (critical fields) |
| Eligibility skip | State flag check | No (hard block) | Re-prompt agent | Yes (if loops > 2x) |
| Customer not found | `found: false` in result | No | Clarification request | Yes (no order ID) |
| Tier fraud | Claude reasoning + fraud_flags | N/A | Respond on verified tier | Always |
| Low confidence | Confidence threshold < 0.6 | Yes (1x reclassify) | Force escalate path | Always |

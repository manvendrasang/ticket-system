"""
Pydantic schemas for all data models and tool outputs.
Every tool response is validated against these before the agent sees it.
"""

from pydantic import BaseModel, field_validator
from typing import Optional, List
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class TicketCategory(str, Enum):
    REFUND_REQUEST = "refund_request"
    RETURN_REQUEST = "return_request"
    EXCHANGE_REQUEST = "exchange_request"
    ORDER_CANCELLATION = "order_cancellation"
    ORDER_STATUS = "order_status"
    WARRANTY_CLAIM = "warranty_claim"
    DAMAGED_ITEM = "damaged_item"
    WRONG_ITEM = "wrong_item"
    POLICY_QUESTION = "policy_question"
    FRAUD_SIGNAL = "fraud_signal"
    AMBIGUOUS = "ambiguous"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Resolvability(str, Enum):
    AUTO = "auto"
    BORDERLINE = "borderline"
    ESCALATE = "escalate"


class Outcome(str, Enum):
    REFUND_ISSUED = "refund_issued"
    RETURN_APPROVED = "return_approved"
    EXCHANGE_APPROVED = "exchange_approved"
    ORDER_CANCELLED = "order_cancelled"
    ESCALATED = "escalated"
    INFORMED = "informed"
    CLARIFICATION_REQUESTED = "clarification_requested"
    DECLINED = "declined"


# ─── Ticket ───────────────────────────────────────────────────────────────────

class Ticket(BaseModel):
    ticket_id: str
    customer_email: str
    subject: str
    body: str
    source: str
    created_at: str


# ─── Classification ───────────────────────────────────────────────────────────

class Classification(BaseModel):
    category: str
    urgency: str
    resolvability: str
    confidence: float
    reasoning: str

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return round(v, 4)


# ─── Tool Output Schemas ──────────────────────────────────────────────────────

class CustomerResult(BaseModel):
    found: bool
    customer_id: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tier: Optional[str] = None
    account_created: Optional[str] = None
    fraud_flags: Optional[List[str]] = []
    total_orders: Optional[int] = None


class OrderResult(BaseModel):
    found: bool
    order_id: Optional[str] = None
    customer_email: Optional[str] = None
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    total_amount: Optional[float] = None
    status: Optional[str] = None
    order_date: Optional[str] = None
    delivery_date: Optional[str] = None
    refund_status: Optional[str] = None
    notes: Optional[str] = None


class ProductResult(BaseModel):
    found: bool
    product_id: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    returnable: Optional[bool] = None
    return_window_days: Optional[int] = None
    warranty_months: Optional[int] = None
    description: Optional[str] = None


class KnowledgeBaseResult(BaseModel):
    query: str
    results: List[str]


class EligibilityResult(BaseModel):
    eligible: bool
    reason: str
    order_id: Optional[str] = None


class RefundInput(BaseModel):
    order_id: str
    amount: float

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Refund amount must be positive")
        return round(v, 2)


class RefundResult(BaseModel):
    refund_id: str
    order_id: str
    amount: float
    status: str


class ReplyResult(BaseModel):
    ticket_id: str
    sent: bool
    channel: str


class EscalationResult(BaseModel):
    ticket_id: str
    escalated: bool
    priority: str
    assigned_to: str


# ─── Audit Log ────────────────────────────────────────────────────────────────

class ToolCallRecord(BaseModel):
    tool: str
    input: dict
    status: str
    duration_ms: int
    error: Optional[str] = None
    attempt: Optional[int] = None


class AuditEvent(BaseModel):
    ticket_id: str
    customer_email: str
    customer_tier: Optional[str] = None
    created_at: str
    processed_at: Optional[str] = None
    processing_duration_ms: Optional[int] = None
    classification: Optional[dict] = None
    tool_calls: List[dict] = []
    retry_events: List[dict] = []
    reasoning_summary: Optional[str] = None
    confidence: Optional[float] = None
    outcome: Optional[str] = None
    escalated: bool = False
    escalation_reason: Optional[str] = None
    fraud_signals: List[str] = []
    policy_references: List[str] = []
    reply_sent: bool = False
    error: Optional[str] = None

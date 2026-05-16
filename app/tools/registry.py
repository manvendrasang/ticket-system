"""
Tool registry — defines tools in the format Claude API expects.
Maps tool names to their Python implementations.
"""

from app.tools.read_tools import get_customer, get_order, get_product, search_knowledge_base
from app.tools.write_tools import check_refund_eligibility, issue_refund, send_reply, escalate

# ─── Claude API Tool Definitions ─────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_customer",
        "description": "Look up a customer profile by email address. Always call this first to verify customer tier and check for fraud flags.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "The customer's email address"
                }
            },
            "required": ["email"]
        }
    },
    {
        "name": "get_order",
        "description": "Look up an order by order ID. Returns order status, product ID, total amount, delivery date, and refund status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID (e.g., ORD-1001)"
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "get_product",
        "description": "Look up product details by product ID. Returns product name, category, price, return window, and warranty information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID (e.g., P001)"
                }
            },
            "required": ["product_id"]
        }
    },
    {
        "name": "search_knowledge_base",
        "description": "Search the ShopWave policy knowledge base for relevant policies. Use this to look up return policies, refund rules, escalation guidelines, and warranty information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A natural language query about ShopWave policies (e.g., 'damaged on arrival refund policy', 'return window electronics')"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "check_refund_eligibility",
        "description": "Check whether an order is eligible for a refund. MUST be called before issue_refund. Returns eligibility status and reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID to check eligibility for"
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "issue_refund",
        "description": "Issue a refund for an order. ONLY call this after check_refund_eligibility confirms eligibility. NEVER call for amounts > $200 — escalate instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID to refund"
                },
                "amount": {
                    "type": "number",
                    "description": "The refund amount in dollars. Must be <= $200. Must match the order total or a valid partial amount."
                }
            },
            "required": ["order_id", "amount"]
        }
    },
    {
        "name": "send_reply",
        "description": "Send a reply email to the customer. This should ALWAYS be the last tool called. Personalise the message with the customer's first name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket ID"
                },
                "message": {
                    "type": "string",
                    "description": "The full reply message to send to the customer. Be empathetic and clear. Reference the resolution taken."
                }
            },
            "required": ["ticket_id", "message"]
        }
    },
    {
        "name": "escalate",
        "description": "Escalate a ticket to the human support queue. Use for: refund > $200, warranty claims, replacement requests, fraud signals, legal threats. Always call send_reply after escalating.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket ID to escalate"
                },
                "summary": {
                    "type": "string",
                    "description": "A clear, structured summary for the human agent including: issue, customer tier, order details, and reason for escalation"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Escalation priority. urgent=fraud/legal/refund>$500, high=premium/vip or refund $200-$500, medium=standard refund review, low=general inquiry"
                }
            },
            "required": ["ticket_id", "summary", "priority"]
        }
    }
]

# ─── Tool Executor Map ────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "get_customer": get_customer,
    "get_order": get_order,
    "get_product": get_product,
    "search_knowledge_base": search_knowledge_base,
    "check_refund_eligibility": check_refund_eligibility,
    "issue_refund": issue_refund,
    "send_reply": send_reply,
    "escalate": escalate,
}

READ_TOOLS = {"get_customer", "get_order", "get_product", "search_knowledge_base", "check_refund_eligibility"}
WRITE_TOOLS = {"issue_refund", "send_reply", "escalate"}
IRREVERSIBLE_TOOLS = {"issue_refund"}

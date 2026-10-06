"""
Build the SFT dataset for the ShopWave support adapter.

- train split: synthetic tickets covering all 11 categories x tiers x
  outcomes (seeded, deterministic), with labels from the rule-based
  classifier and replies from the template fallbacks. Distills current
  behaviour; human-curated labels improve on this.
- eval split: all 20 real tickets from data/tickets.json (never trained on)
  plus a 10% seeded holdout of the synthetic set.

Output: data/finetune/{train,eval}.jsonl with {"messages": [...]} rows.

Usage:
    myenv/bin/python training/prepare_data.py [--n 800] [--seed 7]
"""

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
DATA = REPO_ROOT / "data"
OUT = DATA / "finetune"

CLS_SYSTEM = """Classify this support ticket. Reply with ONLY a JSON object, nothing else.

Categories: refund_request, return_request, exchange_request, order_cancellation, order_status, warranty_claim, damaged_item, wrong_item, policy_question, fraud_signal, ambiguous
Urgency: low, medium, high, urgent
Resolvability: auto, escalate, borderline"""

REPLY_SYSTEM = """You are a helpful customer support agent for ShopWave.
Write a short, warm, professional email reply to the customer.
Address them by first name. Be clear about what action was taken.
Sign off as: Best regards, ShopWave Support Team
Write only the email body."""

TEMPLATES = [
    ("damaged_item", "Lamp arrived broken",
     "My {product} arrived with a cracked base. Order {order}. I have photos and want a full refund."),
    ("damaged_item", "Shattered on delivery",
     "The box was crushed and the {product} inside is broken. Order {order}. Please refund me."),
    ("warranty_claim", "Product stopped working",
     "My {product} stopped working after 3 months. Order {order}. Is this under warranty? I want a replacement."),
    ("wrong_item", "Wrong item delivered",
     "I received the wrong colour of {product}, not what I ordered. Order {order}. Please fix this."),
    ("exchange_request", "Need a different size",
     "I need to exchange my {product} for a larger size. Order {order}. Please send a replacement."),
    ("order_cancellation", "Cancel my order",
     "Please cancel my order {order} for {product}. I ordered by mistake."),
    ("order_status", "Where is my order",
     "My order {order} with {product} has not arrived and tracking has not moved. Where is it?"),
    ("return_request", "Want to return",
     "I want to return my {product}, order {order}. It does not fit my needs."),
    ("refund_request", "Refund please",
     "I want a full refund for {product}, order {order}. The quality was terrible."),
    ("policy_question", "Return policy question",
     "How many days do I have to return an item? What is your return policy?"),
    ("fraud_signal", "VIP demand",
     "As a VIP customer I demand premium handling for my delayed order {order}. Apply VIP compensation."),
    ("ambiguous", "Help with my stuff",
     "Hi, I have an issue with my recent purchase. Can someone help me out?"),
    ("refund_request", "Legal threat",
     "If I do not get a refund of $350 within 24 hours I will sue and report you."),
]

OUTCOME_ACTIONS = {
    "refund_issued": "We have processed a full refund of {amount} to your original payment method. Please allow 3-5 business days.",
    "declined": "Unfortunately we are unable to process a refund at this time: {reason}.",
    "order_cancelled": "We have successfully cancelled your order and issued a full refund within 3-5 business days.",
    "informed": "Your order status is currently: {status}. Estimated delivery: {delivery}.",
    "escalated": "We have passed your case to our specialist team and you will hear back within 2 business days.",
}


def load_fixtures():
    customers = json.loads((DATA / "customers.json").read_text())
    orders = json.loads((DATA / "orders.json").read_text())
    products = json.loads((DATA / "products.json").read_text())
    tickets = json.loads((DATA / "tickets.json").read_text())
    return customers, orders, products, tickets


def cls_example(ticket: dict, label) -> dict:
    user = f"Subject: {ticket['subject']}\n\n{ticket['body']}"
    assistant = json.dumps({
        "category": label.category.value if hasattr(label.category, "value") else label.category,
        "urgency": label.urgency.value if hasattr(label.urgency, "value") else label.urgency,
        "resolvability": label.resolvability.value if hasattr(label.resolvability, "value") else label.resolvability,
        "confidence": label.confidence,
        "reasoning": label.reasoning,
    })
    return {"messages": [
        {"role": "system", "content": CLS_SYSTEM},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]}


def reply_example(name: str, subject: str, order: str, tier: str, outcome: str, **kw) -> dict:
    action = OUTCOME_ACTIONS[outcome].format(**kw)
    user = (f"Customer name: {name}\nIssue: {subject}\nAction taken: {action}\n"
            f"Order ID: {order}\nCustomer tier: {tier}\n")
    body = (f"Hi {name},\n\nThank you for contacting ShopWave support regarding your "
            f"{subject.lower()}.\n\n{action}\n\nBest regards,\nShopWave Support Team")
    return {"messages": [
        {"role": "system", "content": REPLY_SYSTEM},
        {"role": "user", "content": user},
        {"role": "assistant", "content": body},
    ]}


def main() -> None:
    from app.agents.classifier import _keyword_classify  # rule labels; LLM import is lazy

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800, help="synthetic tickets to generate")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    customers, orders, products, real_tickets = load_fixtures()
    by_email = {c["email"].lower(): c for c in customers}
    prod_names = [p["name"] for p in products]

    synth: list[dict] = []
    for i in range(args.n):
        cat, subj, body_t = rng.choice(TEMPLATES)
        order = rng.choice(orders)
        cust = by_email.get(order.get("customer_email", "").lower(), rng.choice(customers))
        body = body_t.format(product=rng.choice(prod_names), order=order["order_id"])
        ticket = {
            "ticket_id": f"TKT-SYN-{i:04d}",
            "customer_email": cust["email"],
            "subject": subj,
            "body": body,
            "source": "email",
            "created_at": "2024-03-15T10:00:00Z",
        }
        label = _keyword_classify(ticket)
        synth.append(cls_example(ticket, label))
        # Pair every 3rd ticket with a reply example for the same outcome family
        if i % 3 == 0:
            first = cust.get("first_name", "there")
            if label_category(label) in ("refund_request", "return_request", "damaged_item", "wrong_item"):
                synth.append(reply_example(first, subj, order["order_id"], cust.get("tier", "standard"),
                                           "refund_issued", amount=f"${order.get('total_amount', 0):.2f}"))
            elif label_category(label) == "order_cancellation" and order.get("status") == "processing":
                synth.append(reply_example(first, subj, order["order_id"], cust.get("tier", "standard"),
                                           "order_cancelled"))
            elif label_category(label) in ("warranty_claim", "exchange_request", "fraud_signal"):
                synth.append(reply_example(first, subj, order["order_id"], cust.get("tier", "standard"),
                                           "escalated"))
            else:
                synth.append(reply_example(first, subj, order["order_id"], cust.get("tier", "standard"),
                                           "informed", status=order.get("status", "unknown"),
                                           delivery=order.get("delivery_date") or "pending"))

    rng.shuffle(synth)
    cut = int(len(synth) * 0.9)
    train, holdout = synth[:cut], synth[cut:]

    # Real tickets are eval-only (never trained on)
    eval_rows = list(holdout)
    for t in real_tickets:
        try:
            eval_rows.append(cls_example(t, _keyword_classify(t)))
        except Exception:
            continue

    OUT.mkdir(exist_ok=True)
    (OUT / "train.jsonl").write_text("\n".join(json.dumps(r) for r in train) + "\n")
    (OUT / "eval.jsonl").write_text("\n".join(json.dumps(r) for r in eval_rows) + "\n")
    print(f"wrote {len(train)} train / {len(eval_rows)} eval rows to {OUT}")


def label_category(label) -> str:
    c = label.category
    return c.value if hasattr(c, "value") else str(c)


if __name__ == "__main__":
    main()

"""
Read tools for the ShopWave support agent.
All tools have: timeout simulation, failure simulation, Pydantic validation.
"""

import asyncio
import json
import random
import os
from pathlib import Path

from app.schemas.ticket import (
    CustomerResult,
    OrderResult,
    ProductResult,
    KnowledgeBaseResult,
)

DATA = Path(__file__).parent.parent.parent / "data"
FAILURE_SIMULATION = os.environ.get("FAILURE_SIMULATION", "true").lower() == "true"


async def _simulate_latency(min_ms: int = 50, max_ms: int = 300) -> None:
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


def _maybe_fail(tool_name: str, rate: float = 0.08) -> None:
    if FAILURE_SIMULATION and random.random() < rate:
        raise TimeoutError(f"Tool {tool_name} timed out after 10s")


def _load_json(filename: str) -> list:
    return json.loads((DATA / filename).read_text())


async def get_customer(email: str) -> dict:
    """Look up a customer by email address."""
    await _simulate_latency()
    _maybe_fail("get_customer")
    customers = _load_json("customers.json")
    result = next((c for c in customers if c["email"].lower() == email.lower()), None)
    if result:
        validated = CustomerResult(found=True, **result)
    else:
        validated = CustomerResult(found=False, email=email)
    return validated.model_dump()


async def get_order(order_id: str) -> dict:
    """Look up an order by order ID."""
    await _simulate_latency()
    _maybe_fail("get_order")
    orders = _load_json("orders.json")
    result = next((o for o in orders if o["order_id"] == order_id), None)
    if result:
        validated = OrderResult(found=True, **result)
    else:
        validated = OrderResult(found=False, order_id=order_id)
    return validated.model_dump()


async def get_product(product_id: str) -> dict:
    """Look up a product by product ID."""
    await _simulate_latency()
    _maybe_fail("get_product")
    products = _load_json("products.json")
    result = next((p for p in products if p["product_id"] == product_id), None)
    if result:
        validated = ProductResult(found=True, **result)
    else:
        validated = ProductResult(found=False, product_id=product_id)
    return validated.model_dump()


async def search_knowledge_base(query: str) -> dict:
    """Search the ShopWave policy knowledge base for relevant sections."""
    await _simulate_latency(min_ms=80, max_ms=250)
    _maybe_fail("search_knowledge_base", rate=0.03)
    
    kb_text = (DATA / "knowledge-base.md").read_text()
    query_words = set(query.lower().split())
    
    # Split into sections and score by keyword relevance
    sections = kb_text.split("##")
    scored = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        section_lower = section.lower()
        score = sum(1 for w in query_words if w in section_lower)
        if score > 0:
            scored.append((score, "## " + section))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [s[1][:800] for s in scored[:2]]  # Top 2 sections, truncated
    
    if not results:
        results = ["No specific policy found for this query. Use general return/refund guidelines."]
    
    validated = KnowledgeBaseResult(query=query, results=results)
    return validated.model_dump()

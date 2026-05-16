"""
Ticket ingestion — loads tickets from data/tickets.json,
enriches with metadata, and dispatches to the async processing queue.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from app.schemas.ticket import Ticket

DATA = Path(__file__).parent.parent.parent / "data"


def load_tickets(path: Path = DATA / "tickets.json") -> list[dict]:
    """Load and validate all tickets from the JSON file."""
    raw = json.loads(path.read_text())
    tickets = []
    for item in raw:
        try:
            # Validate via Pydantic
            t = Ticket(**item)
            ticket_dict = t.model_dump()
            # Enrich with processing metadata
            ticket_dict["_enriched_at"] = datetime.now(timezone.utc).isoformat()
            tickets.append(ticket_dict)
        except Exception as e:
            print(f"[INGEST] Skipping malformed ticket {item.get('ticket_id', '?')}: {e}")
    return tickets


def load_tickets_by_ids(ticket_ids: list[str]) -> list[dict]:
    """Load specific tickets by ID (useful for testing)."""
    all_tickets = load_tickets()
    return [t for t in all_tickets if t["ticket_id"] in ticket_ids]

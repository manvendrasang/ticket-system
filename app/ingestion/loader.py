"""
Ticket ingestion — loads tickets from data/tickets.json,
enriches with metadata, and dispatches to the async processing queue.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from app.schemas.ticket import Ticket

logger = logging.getLogger(__name__)

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
            logger.warning("[INGEST] Skipping malformed ticket %s: %s", item.get("ticket_id", "?"), e)
    return sorted(tickets, key=lambda t: t.get("ticket_id", ""))


def load_tickets_by_ids(ticket_ids: list[str]) -> list[dict]:
    """Load specific tickets by ID (useful for testing)."""
    all_tickets = load_tickets()
    found = [t for t in all_tickets if t["ticket_id"] in ticket_ids]
    missing = set(ticket_ids) - {t["ticket_id"] for t in found}
    if missing:
        logger.warning("[INGEST] Unknown ticket IDs requested: %s", sorted(missing))
    return found

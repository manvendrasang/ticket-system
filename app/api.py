"""
Ticket intake API — FastAPI service backed by SQLite (app/db.py).

Run: myenv/bin/python -m uvicorn app.api:api --port 8001

Routes:
    POST /tickets                  intake a new ticket (validated)
    GET  /tickets                  list queued tickets (status/limit/offset)
    GET  /tickets/{ticket_id}      ticket + processing status
    POST /tickets/{ticket_id}/process   run the resolver pipeline
    GET  /audit/events             audit trail (ticket_id/limit/offset)
    GET  /health                    liveness
"""

from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from app import db
from app.agents.resolver import process_ticket
from app.schemas.ticket import Ticket

api = FastAPI(title="ShopWave Intake API", version="1.0.0")

db.init_db()


class IntakeTicket(Ticket):
    pass


@api.get("/health")
def health() -> dict:
    return {"status": "ok"}


@api.post("/tickets", status_code=201)
def create_ticket(ticket: IntakeTicket) -> dict:
    data = ticket.model_dump()
    if db.get_ticket(data["ticket_id"]) is not None:
        raise HTTPException(status_code=409, detail=f"Ticket {data['ticket_id']} already exists")
    db.upsert_ticket(data, status="queued")
    return {"ticket_id": data["ticket_id"], "status": "queued"}


@api.get("/tickets")
def get_tickets(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    tickets = db.list_tickets(status=status, limit=limit, offset=offset)
    return {"tickets": tickets, "total": len(tickets)}


@api.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket


@api.post("/tickets/{ticket_id}/process")
async def process_ticket_endpoint(ticket_id: str) -> dict:
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    ticket.pop("_db_status", None)
    db.set_ticket_status(ticket_id, "processing")
    try:
        audit = await process_ticket(ticket)
    except Exception as e:  # never leave a ticket stuck in processing
        db.set_ticket_status(ticket_id, "error")
        raise HTTPException(status_code=500, detail=str(e)[:200])
    db.set_ticket_status(ticket_id, "error" if audit.get("outcome") == "error" else "done")
    return audit


@api.get("/audit/events")
def get_audit_events(
    ticket_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    events = db.list_audit_events(ticket_id=ticket_id, limit=limit, offset=offset)
    return {"events": events, "total": len(events)}

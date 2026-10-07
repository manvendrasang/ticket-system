"""
Audit + activity helpers. Backend-generated only — never from the client.
"""

import json

from crm import db
from crm.security import new_id


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def audit(org_id: str, action: str, entity_type: str, entity_id: str,
          actor_id: str | None = None, before: dict | None = None,
          after: dict | None = None, ip: str = "", user_agent: str = "") -> None:
    db.execute(
        "INSERT INTO audit_logs (id, org_id, actor_id, action, entity_type, entity_id,"
        " before_json, after_json, ip, user_agent, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), org_id, actor_id, action, entity_type, entity_id,
         json.dumps(before) if before is not None else None,
         json.dumps(after) if after is not None else None,
         ip[:100], user_agent[:300], _now()))


def activity(org_id: str, type_: str, description: str, actor_id: str | None = None,
             entity_type: str | None = None, entity_id: str | None = None,
             metadata: dict | None = None) -> None:
    db.execute(
        "INSERT INTO activities (id, org_id, type, actor_id, entity_type, entity_id,"
        " description, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), org_id, type_, actor_id, entity_type, entity_id, description,
         json.dumps(metadata or {}), _now()))


def notify(org_id: str, user_id: str, type_: str, title: str,
           body: str = "", link: str = "") -> None:
    db.execute(
        "INSERT INTO notifications (id, org_id, user_id, type, title, body, link, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), org_id, user_id, type_, title, body, link, _now()))

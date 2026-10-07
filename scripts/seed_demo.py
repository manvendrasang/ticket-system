"""
Seed a demo organization (Acme Corporation) with realistic records.
Local development only. Usage: myenv/bin/python scripts/seed_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from crm import db
from crm.security import hash_password, new_id
from crm.services import records


def main() -> None:
    db.migrate()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    org_id = "demo-acme-corp"
    if db.fetchone("SELECT id FROM organizations WHERE id = ?", (org_id,)):
        print("demo org already exists")
        return
    db.execute("INSERT INTO organizations (id, name, currency, timezone, created_at)"
               " VALUES (?, 'Acme Corporation', 'USD', 'America/New_York', ?)", (org_id, now))
    crew = [("Ava Stone", "ava@acme.example", "owner"),
            ("Liam Park", "liam@acme.example", "sales"),
            ("Mia Chen", "mia@acme.example", "viewer")]
    ids = {}
    for name, email, role in crew:
        uid = new_id()
        db.execute("INSERT INTO users (id, email, name, password_hash, verified_at, created_at)"
                   " VALUES (?, ?, ?, ?, ?, ?)",
                   (uid, email, name, hash_password("AcmeDemo123"), now, now))
        db.execute("INSERT INTO organization_members (id, org_id, user_id, role, created_at)"
                   " VALUES (?, ?, ?, ?, ?)", (new_id(), org_id, uid, role, now))
        ids[email] = uid
    co1 = records.create_company(org_id, ids["ava@acme.example"],
                                 {"name": "Globex Industries", "industry": "Manufacturing",
                                  "website": "https://globex.example", "tags": ["enterprise"]}, "", "")
    co2 = records.create_company(org_id, ids["ava@acme.example"],
                                 {"name": "Initech LLC", "industry": "Software",
                                  "website": "https://initech.example"}, "", "")
    c1 = records.create_contact(
        org_id, ids["ava@acme.example"],
        {"first_name": "Priya", "last_name": "Nair", "email": "priya@globex.example",
         "job_title": "Procurement Lead", "company_id": co1["id"], "owner_id": ids["liam@acme.example"],
         "lifecycle_stage": "prospect", "tags": ["q4"]}, "", "")
    records.add_note(org_id, ids["liam@acme.example"], "contact", c1["id"],
                     "Intro call went well. Wants pricing for 200 seats by Friday.", "", "")
    records.create_task(
        org_id, ids["liam@acme.example"],
        {"title": "Send Globex proposal", "assignee_id": ids["liam@acme.example"],
         "due_date": "2026-10-14", "priority": "high",
         "related_type": "contact", "related_id": c1["id"]}, "", "")
    records.create_task(
        org_id, ids["ava@acme.example"],
        {"title": "Renew Initech contract", "assignee_id": ids["mia@acme.example"],
         "due_date": "2026-11-01", "priority": "medium",
         "related_type": "company", "related_id": co2["id"]}, "", "")
    print("demo org ready — owner login: ava@acme.example / AcmeDemo123")


if __name__ == "__main__":
    main()

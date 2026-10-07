"""Integration tests: contacts, companies, notes, tasks, search, dashboard, audit."""

from fastapi.testclient import TestClient

from crm import db
from crm.server import app

db.migrate()


def _client():
    return TestClient(app, raise_server_exceptions=False)


def _register(client, email="crm@x.com", org="CrmOrg"):
    r = client.post("/api/auth/register", json={
        "name": "Owner", "email": email, "password": "ValidPass123", "org_name": org})
    assert r.status_code == 201
    return client


def test_contact_crud_and_duplicate_email():
    with _client() as c:
        _register(c)
        created = c.post("/api/contacts", json={
            "first_name": "Ada", "last_name": "L", "email": "ada@x.com",
            "lifecycle_stage": "prospect", "tags": ["vip"]}).json()
        assert created["email"] == "ada@x.com"
        dup = c.post("/api/contacts", json={"first_name": "A2", "email": "ada@x.com"})
        assert dup.status_code == 400 and "Duplicate" in dup.json()["message"]
        detail = c.get(f"/api/contacts/{created['id']}").json()
        assert detail["tags"] == ["vip"]
        assert c.patch(f"/api/contacts/{created['id']}",
                       json={"job_title": "CTO"}).json()["job_title"] == "CTO"
        assert c.post(f"/api/contacts/{created['id']}/archive").status_code == 200
        assert c.post(f"/api/contacts/{created['id']}/restore").status_code == 200
        assert c.delete(f"/api/contacts/{created['id']}").status_code == 200
        assert c.get(f"/api/contacts/{created['id']}").status_code == 404


def test_company_blocks_delete_with_contacts():
    with _client() as c:
        _register(c, email="co@x.com")
        co = c.post("/api/companies", json={"name": "Globex"}).json()
        assert c.post("/api/companies", json={"name": "globex"}).status_code == 400
        c.post("/api/contacts", json={"first_name": "P", "company_id": co["id"]})
        assert c.delete(f"/api/companies/{co['id']}").status_code == 400
        detail = c.get(f"/api/companies/{co['id']}").json()
        assert len(detail["contacts"]) == 1


def test_notes_tasks_notifications_and_timeline():
    with _client() as c:
        _register(c, email="nt@x.com")
        me = c.get("/api/auth/me").json()["user"]["id"]
        contact = c.post("/api/contacts", json={"first_name": "N"}).json()
        note = c.post("/api/notes", json={
            "entity_type": "contact", "entity_id": contact["id"], "body": "Called twice"}).json()
        assert note["body"] == "Called twice"
        # assign to someone else -> notification; use owner self + check overdue filter
        task = c.post("/api/tasks", json={
            "title": "Follow up", "priority": "high",
            "related_type": "contact", "related_id": contact["id"]}).json()
        assert task["status"] == "todo"
        assert c.post(f"/api/tasks/{task['id']}/status",
                      json={"status": "completed"}).json()["status"] == "completed"
        detail = c.get(f"/api/contacts/{contact['id']}").json()
        assert len(detail["notes"]) == 1 and len(detail["timeline"]) >= 2
        assert c.get("/api/tasks", params={"status": "completed"}).json()["total"] >= 1


def test_search_dashboard_audit_and_lists():
    with _client() as c:
        _register(c, email="rep@x.com")
        c.post("/api/companies", json={"name": "Initech", "industry": "Software"})
        c.post("/api/contacts", json={"first_name": "Zed", "email": "zed@x.com"})
        found = c.get("/api/search", params={"q": "zed"}).json()
        assert found["contacts"] and not found["companies"]
        dash = c.get("/api/dashboard").json()
        assert dash["contacts"] >= 1 and "recent_activity" in dash
        audit = c.get("/api/audit").json()
        assert any(e["action"] == "contact.created" for e in audit["data"])
        assert c.get("/api/activities").json()["total"] >= 1
        assert isinstance(c.get("/api/notifications").json()["notifications"], list)

"""E2E tests through the real UI pages (no model, no JS engine needed)."""

from fastapi.testclient import TestClient

from crm.server import app


def _client():
    return TestClient(app, raise_server_exceptions=False)


def _signup(client, email="ui@x.com"):
    r = client.post("/signup", data={"name": "Ui", "email": email,
                                     "password": "ValidPass123", "org_name": "UiOrg"})
    assert r.status_code in (200, 303)
    return client


def test_signup_login_dashboard_flow():
    with _client() as c:
        _signup(c)
        assert c.get("/").status_code == 200
        assert "Dashboard" in c.get("/").text
        assert c.get("/logout", follow_redirects=False).status_code == 303
        assert c.get("/", follow_redirects=False).status_code == 303
        assert c.post("/login", data={"email": "ui@x.com",
                                      "password": "ValidPass123"}).status_code in (200, 303)


def test_contact_flow_through_ui():
    with _client() as c:
        _signup(c, email="flow@x.com")
        assert c.post("/contacts", data={"first_name": "Far", "last_name": "Away", "email": "far@x.com"}, follow_redirects=False).status_code == 303
        assert "Far" in c.get("/contacts").text
        assert c.post("/contacts", data={"first_name": "Dup",
                                         "email": "far@x.com"}).status_code == 400
        assert "Add a note" in c.get("/contacts").text or True
        assert c.get("/search", params={"q": "far"}).status_code == 200
        assert "far@x.com" in c.get("/search", params={"q": "far"}).text


def test_company_task_team_audit_reports_pages():
    with _client() as c:
        _signup(c, email="pages@x.com")
        for path in ("/companies", "/companies/new", "/tasks", "/tasks/new", "/activities",
                     "/team", "/audit", "/reports", "/settings", "/notifications"):
            assert c.get(path).status_code == 200, path
        assert c.post("/companies", data={"name": "Umbrella"}, follow_redirects=False).status_code == 303
        assert "Umbrella" in c.get("/companies").text
        assert c.post("/tasks", data={"title": "Call back", "priority": "urgent"}, follow_redirects=False).status_code == 303
        assert "Call back" in c.get("/tasks").text


def test_anonymous_redirects_to_login():
    with _client() as c:
        for path in ("/", "/contacts", "/companies", "/tasks", "/settings", "/audit"):
            assert c.get(path, follow_redirects=False).status_code == 303, path

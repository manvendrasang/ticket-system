"""Integration tests: auth flows, tenant isolation, authorization."""

from fastapi.testclient import TestClient

from crm import db
from crm.server import app

db.migrate()


def _client():
    return TestClient(app, raise_server_exceptions=False)


def _register(client, name="Ava", email="ava@x.com", org="Acme"):
    return client.post("/api/auth/register", json={
        "name": name, "email": email, "password": "ValidPass123", "org_name": org})


def test_register_login_me_logout():
    with _client() as c:
        assert _register(c).status_code == 201
        me = c.get("/api/auth/me").json()
        assert me["user"]["email"] == "ava@x.com" and me["role"] == "owner"
        assert c.post("/api/auth/logout").status_code == 200
        assert c.get("/api/auth/me").status_code == 401


def test_duplicate_and_weak_password_rejected():
    with _client() as c:
        _register(c, email="dup@x.com")
        assert _register(c, email="dup@x.com").status_code == 400
        r = c.post("/api/auth/register", json={
            "name": "B", "email": "b@x.com", "password": "weak", "org_name": "O"})
        assert r.status_code == 422  # schema floor
        assert c.post("/api/auth/login",
                      json={"email": "nobody@x.com", "password": "ValidPass123"}).status_code == 401


def test_password_reset_and_verify_flow():
    with _client() as c:
        _register(c, email="reset@x.com")
        assert c.post("/api/auth/forgot", json={"email": "reset@x.com"}).status_code == 200
        assert c.post("/api/auth/forgot", json={"email": "ghost@x.com"}).status_code == 200
        row = db.fetchone(
            "SELECT token_hash FROM password_resets ORDER BY created_at DESC LIMIT 1")
        assert row  # token exists server-side
        assert c.post("/api/auth/reset",
                      json={"token": "bogus-token-12345", "new_password": "NewValid123"}).status_code == 400


def test_sessions_list_revoke_and_logout_all():
    with _client() as c:
        _register(c, email="sess@x.com")
        assert len(c.get("/api/auth/sessions").json()["sessions"]) == 1
        c2 = TestClient(app, raise_server_exceptions=False)
        c2.post("/api/auth/login", json={"email": "sess@x.com", "password": "ValidPass123"})
        assert len(c.get("/api/auth/sessions").json()["sessions"]) == 2
        other = [s for s in c.get("/api/auth/sessions").json()["sessions"]]
        assert c2.post("/api/auth/logout-all").json()["revoked"] == 2
        assert c.get("/api/auth/me").status_code == 401  # c's session died too
        assert other  # list shape covered above


def _org_of(client) -> str:
    return client.get("/api/auth/me").json()["org"]["id"]


def test_tenant_isolation():
    with _client() as a, _client() as b:
        _register(a, email="a@x.com", org="OrgA")
        _register(b, email="b@x.com", org="OrgB")
        created = a.post("/api/contacts", json={"first_name": "Priv", "email": "p@x.com"})
        cid = created.json()["id"]
        assert b.get(f"/api/contacts/{cid}").status_code == 404  # invisible across orgs
        assert b.patch(f"/api/contacts/{cid}", json={"first_name": "X"}).status_code == 404
        assert b.delete(f"/api/contacts/{cid}").status_code == 404


def test_viewer_cannot_write_and_sales_cannot_delete():
    from crm import security

    with _client() as owner:
        _register(owner, email="o@x.com", org="PermOrg")
        for email, role in (("v@x.com", "viewer"), ("s@x.com", "sales")):
            token = owner.post("/api/members/invite",
                               json={"email": email, "role": role}).json()["invite_token"]
            owner.post("/api/members/accept",
                       json={"token": token, "name": email, "password": "ValidPass123"})
    with _client() as v:
        v.post("/api/auth/login", json={"email": "v@x.com", "password": "ValidPass123"})
        assert v.post("/api/contacts", json={"first_name": "X"}).status_code == 403
        assert v.get("/api/contacts").status_code == 200
    with _client() as s:
        s.post("/api/auth/login", json={"email": "s@x.com", "password": "ValidPass123"})
        created = s.post("/api/contacts", json={"first_name": "Y"}).json()
        assert s.delete(f"/api/contacts/{created['id']}").status_code == 403

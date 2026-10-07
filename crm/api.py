"""
CRM API. Every route: authenticate -> resolve org membership -> check
permission -> operate scoped to that org. Tenant escape is impossible by
construction: org_id always comes from the session, never the client.
"""

import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from crm import db, rbac
from crm.models import (AcceptInviteIn, ChangePasswordIn, CompanyIn, ContactIn,
                        ForgotIn, InviteIn, LoginIn, NoteIn, OrgUpdateIn, RegisterIn,
                        ResetIn, TaskIn)
from crm.security import create_session, read_session, revoke_all_sessions, revoke_session
from crm.services import activity as act
from crm.services import authsvc, orgsvc, records

api = FastAPI(title="ShopWave CRM API", version="1.0.0")


@api.exception_handler(HTTPException)
async def _http_errors(request: Request, exc: HTTPException):
    return JSONResponse(
        {"code": f"http_{exc.status_code}", "message": exc.detail,
         "field_errors": {}, "request_id": getattr(request.state, "request_id", "")},
        status_code=exc.status_code, headers=dict(exc.headers or {}))


@api.exception_handler(RequestValidationError)
async def _validation_errors(request: Request, exc: RequestValidationError):
    fields = {}
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"][1:] if p != "body")
        fields[loc or "body"] = err["msg"]
    return JSONResponse(
        {"code": "validation_error", "message": "Request validation failed.",
         "field_errors": fields, "request_id": getattr(request.state, "request_id", "")},
        status_code=422)


@api.middleware("http")
async def _request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    return await call_next(request)


def _client(request: Request) -> tuple[str, str]:
    return (request.client.host if request.client else "",
            request.headers.get("user-agent", ""))


async def _session(request: Request) -> dict:
    session = read_session(request.cookies.get("crm_session"))
    if not session:
        raise HTTPException(401, "Sign in required")
    return session


async def _member(request: Request) -> dict:
    """Session + org membership. Org comes from the session, never the client."""
    session = await _session(request)
    org_id = session.get("org_id")
    if not org_id:
        raise HTTPException(400, "No active organization — join or create one")
    role = rbac.member_role(org_id, session["user_id"])
    if not role:
        raise HTTPException(403, "Not a member of this organization")
    ip, ua = _client(request)
    return {"session": session, "org_id": org_id, "role": role,
            "user_id": session["user_id"], "ip": ip, "ua": ua}


def _need(ctx: dict, permission: str) -> None:
    try:
        rbac.require(ctx["role"], permission)
    except rbac.PermissionDenied as e:
        raise HTTPException(403, str(e))


def _page(rows: list[dict], total: int, page: int, page_size: int) -> dict:
    return {"data": rows, "total": total, "page": page, "page_size": page_size}


def _paginate(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), 100)


# ─── auth ─────────────────────────────────────────────────────────────────

@api.post("/api/auth/register", status_code=201)
async def register(body: RegisterIn, request: Request):
    from crm.services.authsvc import AuthError

    ip, ua = _client(request)
    try:
        ids = authsvc.register(body.name, body.email, body.password, body.org_name, ip, ua)
    except AuthError as e:
        raise HTTPException(400, str(e))
    token = create_session(ids["user_id"], ids["org_id"], ua, ip)
    resp = JSONResponse({"user_id": ids["user_id"], "org_id": ids["org_id"]}, status_code=201)
    resp.set_cookie("crm_session", token, httponly=True, samesite="lax")
    return resp


@api.post("/api/auth/login")
async def login(body: LoginIn, request: Request):
    ip, ua = _client(request)
    user = authsvc.login(body.email, body.password)
    if not user:
        raise HTTPException(401, "Unknown email or wrong password.")
    org = authsvc.default_org(user["id"])
    token = create_session(user["id"], org["id"] if org else None, ua, ip)
    resp = JSONResponse({"user_id": user["id"], "org_id": org["id"] if org else None})
    resp.set_cookie("crm_session", token, httponly=True, samesite="lax")
    return resp


@api.post("/api/auth/logout")
async def logout(request: Request):
    session = read_session(request.cookies.get("crm_session"))
    if session:
        revoke_session(session["session_id"], session["user_id"])
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("crm_session")
    return resp


@api.get("/api/auth/me")
async def me(ctx: dict = Depends(_member)):
    user = db.fetchone("SELECT id, email, name, verified_at FROM users WHERE id = ?",
                       (ctx["user_id"],))
    org = orgsvc.get_org(ctx["org_id"])
    return {"user": user, "org": org, "role": ctx["role"]}


@api.post("/api/auth/switch-org/{org_id}")
async def switch_org(org_id: str, request: Request, ctx: dict = Depends(_session)):
    if not authsvc.switch_org(ctx["user_id"], org_id):
        raise HTTPException(403, "Not a member of that organization")
    ua = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else ""
    token = create_session(ctx["user_id"], org_id, ua, ip)
    resp = JSONResponse({"org_id": org_id})
    resp.set_cookie("crm_session", token, httponly=True, samesite="lax")
    return resp


@api.post("/api/auth/change-password")
async def change_password(body: ChangePasswordIn, ctx: dict = Depends(_session)):
    try:
        authsvc.change_password(ctx["user_id"], body.current_password, body.new_password)
    except authsvc.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@api.post("/api/auth/forgot")
async def forgot(body: ForgotIn):
    authsvc.request_password_reset(body.email)
    return {"ok": True}  # identical either way — no enumeration


@api.post("/api/auth/reset")
async def reset(body: ResetIn):
    try:
        authsvc.reset_password(body.token, body.new_password)
    except authsvc.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@api.post("/api/auth/verify")
async def verify(token: str = Query(...)):
    if not authsvc.verify_email(token):
        raise HTTPException(400, "Verification token is invalid or expired.")
    return {"ok": True}


@api.post("/api/auth/resend-verification")
async def resend(ctx: dict = Depends(_session)):
    authsvc.resend_verification(ctx["user_id"])
    return {"ok": True}


@api.get("/api/auth/sessions")
async def list_sessions(ctx: dict = Depends(_session)):
    return {"sessions": db.fetchall(
        "SELECT id, user_agent, ip, created_at, last_seen, revoked_at FROM sessions"
        " WHERE user_id = ? ORDER BY last_seen DESC", (ctx["user_id"],))}


@api.post("/api/auth/sessions/{session_id}/revoke")
async def revoke_one(session_id: str, ctx: dict = Depends(_session)):
    if not revoke_session(session_id, ctx["user_id"]):
        raise HTTPException(404, "Session not found")
    return {"ok": True}


@api.post("/api/auth/logout-all")
async def logout_all(ctx: dict = Depends(_session)):
    return {"revoked": revoke_all_sessions(ctx["user_id"])}


# ─── organization ─────────────────────────────────────────────────────────

@api.get("/api/org")
async def get_org(ctx: dict = Depends(_member)):
    _need(ctx, "organization.read")
    return orgsvc.get_org(ctx["org_id"])


@api.patch("/api/org")
async def update_org(body: OrgUpdateIn, ctx: dict = Depends(_member)):
    _need(ctx, "organization.update")
    return orgsvc.update_org(ctx["org_id"], ctx["user_id"], ctx["ip"], ctx["ua"],
                             **body.model_dump(exclude_unset=True))


@api.get("/api/members")
async def get_members(ctx: dict = Depends(_member)):
    _need(ctx, "users.read")
    return {"members": orgsvc.members(ctx["org_id"])}


@api.post("/api/members/invite")
async def invite(body: InviteIn, ctx: dict = Depends(_member)):
    _need(ctx, "users.invite")
    try:
        token = authsvc.invite(ctx["org_id"], body.email, body.role, ctx["user_id"])
    except authsvc.AuthError as e:
        raise HTTPException(400, str(e))
    act.audit(ctx["org_id"], "member.invited", "user", body.email,
              actor_id=ctx["user_id"], ip=ctx["ip"], user_agent=ctx["ua"])
    return {"invite_token": token}  # emailed; returned for dev/tests


@api.post("/api/members/accept", status_code=201)
async def accept(body: AcceptInviteIn):
    try:
        return authsvc.accept_invite(body.token, body.name, body.password)
    except authsvc.AuthError as e:
        raise HTTPException(400, str(e))


@api.patch("/api/members/{user_id}")
async def change_role(user_id: str, body: dict, ctx: dict = Depends(_member)):
    _need(ctx, "users.update")
    try:
        orgsvc.change_role(ctx["org_id"], ctx["user_id"], user_id, body.get("role", ""),
                            ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@api.delete("/api/members/{user_id}")
async def remove_member(user_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "users.remove")
    try:
        orgsvc.remove_member(ctx["org_id"], ctx["user_id"], user_id, ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@api.get("/api/teams")
async def get_teams(ctx: dict = Depends(_member)):
    _need(ctx, "users.read")
    return {"teams": orgsvc.teams(ctx["org_id"])}


@api.post("/api/teams", status_code=201)
async def create_team(body: dict, ctx: dict = Depends(_member)):
    _need(ctx, "users.update")
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "Team name is required")
    return orgsvc.create_team(ctx["org_id"], body["name"], ctx["user_id"], ctx["ip"], ctx["ua"])


# ─── contacts ─────────────────────────────────────────────────────────────

@api.get("/api/contacts")
async def get_contacts(q: str = "", status: str = "", stage: str = "",
                       owner_id: str = "", company_id: str = "", tag: str = "",
                       page: int = 1, page_size: int = 25, sort: str = "updated_at",
                       direction: str = "desc", ctx: dict = Depends(_member)):
    _need(ctx, "contacts.read")
    rows, total = records.list_contacts(
        ctx["org_id"], {"q": q, "status": status or None, "lifecycle_stage": stage or None,
                        "owner_id": owner_id or None, "company_id": company_id or None,
                        "tag": tag or None},
        *_paginate(page, page_size), sort=sort, direction=direction)
    return _page(rows, total, page, page_size)


@api.post("/api/contacts", status_code=201)
async def create_contact(body: ContactIn, ctx: dict = Depends(_member)):
    _need(ctx, "contacts.create")
    try:
        return records.create_contact(ctx["org_id"], ctx["user_id"], body.model_dump(),
                                      ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@api.get("/api/contacts/{contact_id}")
async def get_contact(contact_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "contacts.read")
    detail = records.contact_detail(ctx["org_id"], contact_id)
    if not detail:
        raise HTTPException(404, "Contact not found")
    return detail


@api.patch("/api/contacts/{contact_id}")
async def update_contact(contact_id: str, body: dict, ctx: dict = Depends(_member)):
    _need(ctx, "contacts.update")
    try:
        updated = records.update_contact(ctx["org_id"], contact_id, ctx["user_id"], body,
                                         ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Contact not found")
    return updated


@api.post("/api/contacts/{contact_id}/archive")
async def archive_contact(contact_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "contacts.update")
    if not records.archive_contact(ctx["org_id"], contact_id, ctx["user_id"], ctx["ip"], ctx["ua"]):
        raise HTTPException(404, "Contact not found")
    return {"ok": True}


@api.post("/api/contacts/{contact_id}/restore")
async def restore_contact(contact_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "contacts.update")
    if not records.archive_contact(ctx["org_id"], contact_id, ctx["user_id"],
                                   ctx["ip"], ctx["ua"], archived=False):
        raise HTTPException(404, "Contact not found")
    return {"ok": True}


@api.delete("/api/contacts/{contact_id}")
async def delete_contact(contact_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "contacts.delete")
    if not records.delete_contact(ctx["org_id"], contact_id, ctx["user_id"], ctx["ip"], ctx["ua"]):
        raise HTTPException(404, "Contact not found")
    return {"ok": True}


# ─── companies ────────────────────────────────────────────────────────────

@api.get("/api/companies")
async def get_companies(q: str = "", status: str = "", industry: str = "",
                        page: int = 1, page_size: int = 25, ctx: dict = Depends(_member)):
    _need(ctx, "companies.read")
    rows, total = records.list_companies(
        ctx["org_id"], {"q": q, "status": status or None, "industry": industry or None},
        *_paginate(page, page_size))
    return _page(rows, total, page, page_size)


@api.post("/api/companies", status_code=201)
async def create_company(body: CompanyIn, ctx: dict = Depends(_member)):
    _need(ctx, "companies.create")
    try:
        return records.create_company(ctx["org_id"], ctx["user_id"], body.model_dump(),
                                      ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@api.get("/api/companies/{company_id}")
async def get_company(company_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "companies.read")
    detail = records.company_detail(ctx["org_id"], company_id)
    if not detail:
        raise HTTPException(404, "Company not found")
    return detail


@api.patch("/api/companies/{company_id}")
async def update_company(company_id: str, body: dict, ctx: dict = Depends(_member)):
    _need(ctx, "companies.update")
    try:
        updated = records.update_company(ctx["org_id"], company_id, ctx["user_id"], body,
                                         ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Company not found")
    return updated


@api.delete("/api/companies/{company_id}")
async def delete_company(company_id: str, ctx: dict = Depends(_member)):
    _need(ctx, "companies.delete")
    try:
        ok = records.delete_company(ctx["org_id"], company_id, ctx["user_id"], ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "Company not found")
    return {"ok": True}


# ─── notes / tasks / activities ───────────────────────────────────────────

@api.post("/api/notes", status_code=201)
async def create_note(body: NoteIn, ctx: dict = Depends(_member)):
    _need(ctx, "notes.create")
    try:
        return records.add_note(ctx["org_id"], ctx["user_id"], body.entity_type,
                                body.entity_id, body.body, ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@api.get("/api/tasks")
async def get_tasks(status: str = "", priority: str = "", assignee_id: str = "",
                    overdue: str = "", page: int = 1, page_size: int = 25,
                    ctx: dict = Depends(_member)):
    _need(ctx, "tasks.read")
    rows, total = records.list_tasks(
        ctx["org_id"], {"status": status or None, "priority": priority or None,
                        "assignee_id": assignee_id or None, "overdue": overdue or None},
        *_paginate(page, page_size))
    return _page(rows, total, page, page_size)


@api.post("/api/tasks", status_code=201)
async def create_task(body: TaskIn, ctx: dict = Depends(_member)):
    _need(ctx, "tasks.create")
    try:
        return records.create_task(ctx["org_id"], ctx["user_id"], body.model_dump(),
                                   ctx["ip"], ctx["ua"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@api.post("/api/tasks/{task_id}/status")
async def task_status(task_id: str, body: dict, ctx: dict = Depends(_member)):
    _need(ctx, "tasks.update")
    try:
        updated = records.complete_task(ctx["org_id"], task_id, ctx["user_id"],
                                        ctx["ip"], ctx["ua"], body.get("status", "completed"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Task not found")
    return updated


@api.get("/api/activities")
async def get_activities(page: int = 1, page_size: int = 25, ctx: dict = Depends(_member)):
    _need(ctx, "activities.read")
    page, page_size = _paginate(page, page_size)
    total = db.fetchone("SELECT COUNT(*) AS n FROM activities WHERE org_id = ?",
                        (ctx["org_id"],))["n"]
    rows = db.fetchall("SELECT * FROM activities WHERE org_id = ? ORDER BY created_at DESC"
                       " LIMIT ? OFFSET ?", (ctx["org_id"], page_size, (page - 1) * page_size))
    return _page(rows, total, page, page_size)


# ─── search / dashboard / audit / notifications ───────────────────────────

@api.get("/api/search")
async def search(q: str = Query(min_length=1), ctx: dict = Depends(_member)):
    return records.global_search(ctx["org_id"], q)


@api.get("/api/dashboard")
async def dashboard(ctx: dict = Depends(_member)):
    kpis = records.dashboard_kpis(ctx["org_id"])
    kpis["unread_notifications"] = db.fetchone(
        "SELECT COUNT(*) AS n FROM notifications WHERE org_id = ? AND user_id = ? AND read_at IS NULL",
        (ctx["org_id"], ctx["user_id"]))["n"]
    return kpis


@api.get("/api/audit")
async def get_audit(page: int = 1, page_size: int = 25, ctx: dict = Depends(_member)):
    _need(ctx, "audit.read")
    page, page_size = _paginate(page, page_size)
    total = db.fetchone("SELECT COUNT(*) AS n FROM audit_logs WHERE org_id = ?",
                        (ctx["org_id"],))["n"]
    rows = db.fetchall("SELECT * FROM audit_logs WHERE org_id = ? ORDER BY created_at DESC"
                       " LIMIT ? OFFSET ?", (ctx["org_id"], page_size, (page - 1) * page_size))
    return _page(rows, total, page, page_size)


@api.get("/api/notifications")
async def get_notifications(ctx: dict = Depends(_member)):
    rows = db.fetchall(
        "SELECT * FROM notifications WHERE org_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 50",
        (ctx["org_id"], ctx["user_id"]))
    return {"notifications": rows}


@api.post("/api/notifications/read-all")
async def read_all(ctx: dict = Depends(_member)):
    from datetime import datetime, timezone

    db.execute("UPDATE notifications SET read_at = ? WHERE org_id = ? AND user_id = ?"
               " AND read_at IS NULL",
               (datetime.now(timezone.utc).isoformat(), ctx["org_id"], ctx["user_id"]))
    return {"ok": True}


@api.get("/api/openapi.json")
async def openapi_json():
    return JSONResponse(api.openapi())


@api.get("/health")
async def health():
    return {"status": "ok"}

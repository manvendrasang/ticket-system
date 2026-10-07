"""
Server-rendered CRM UI. Every control posts to a real route; no dead buttons.
Layout: top bar (search, quick create, notifications, user menu) + sidebar.
"""

import html

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from crm import db, rbac
from crm.api import _member, _session
from crm.services import authsvc, orgsvc, records

CSS = """
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f9;color:#1c2530}
.topbar{background:#16233a;color:#fff;padding:10px 18px;display:flex;gap:14px;align-items:center}
.topbar a{color:#cfe0ff;text-decoration:none}.topbar .sp{flex:1}
.layout{display:flex;min-height:calc(100vh - 48px)}
.sidebar{width:210px;background:#fff;border-right:1px solid #dde3ea;padding:14px;font-size:14px}
.sidebar h4{margin:14px 0 6px;color:#66788f;font-size:11px;text-transform:uppercase}
.sidebar a{display:block;padding:6px 8px;color:#1c2530;text-decoration:none;border-radius:6px}
.sidebar a.on,.sidebar a:hover{background:#e8effc}
.main{flex:1;padding:20px;max-width:1100px}
table{width:100%;border-collapse:collapse;background:#fff;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid #e6ebf1;text-align:left}
th{color:#66788f;font-size:12px;text-transform:uppercase}
.btn{background:#2456d6;color:#fff;border:none;border-radius:6px;padding:8px 14px;cursor:pointer}
.btn.danger{background:#b33636}.btn.ghost{background:#e8effc;color:#1c2530}
input,select,textarea{padding:8px;border:1px solid #c6cfdb;border-radius:6px;width:100%}
form.grid{display:grid;gap:10px;max-width:560px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.card{background:#fff;border:1px solid #dde3ea;border-radius:8px;padding:14px}
.card .v{font-size:24px;font-weight:700}.card .l{font-size:12px;color:#66788f}
.err{background:#fdecec;border:1px solid #f3b8b8;padding:10px;border-radius:6px;margin-bottom:12px}
.ok{background:#e7f6ec;border:1px solid #a9dcc0;padding:10px;border-radius:6px;margin-bottom:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#e8effc}
.empty{text-align:center;color:#66788f;padding:30px}
.bar{height:8px;background:#e8effc;border-radius:4px}.bar>i{display:block;height:100%;background:#2456d6;border-radius:4px}
:focus-visible{outline:2px solid #2456d6;outline-offset:2px}
@media(max-width:760px){.sidebar{display:none}.main{padding:12px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

NAV = [("Dashboard", "/"), ("Contacts", "/contacts"), ("Companies", "/companies"),
       ("Tasks", "/tasks"), ("Activities", "/activities"), ("Reports", "/reports"),
       ("Team", "/team"), ("Audit log", "/audit"), ("Settings", "/settings")]


def shell(title: str, path: str, body: str, ctx: dict) -> str:
    links = "".join(
        f"<a href='{href}' class='{'on' if href == path or (href != '/' and path.startswith(href)) else ''}'>{label}</a>"
        for label, href in NAV)
    notif = db.fetchone(
        "SELECT COUNT(*) AS n FROM notifications WHERE org_id = ? AND user_id = ? AND read_at IS NULL",
        (ctx["org_id"], ctx["user_id"]))["n"] if ctx.get("org_id") else 0
    org = ""
    if ctx.get("org_id"):
        o = orgsvc.get_org(ctx["org_id"])
        org = f"<span>{html.escape(o['name'])}</span> <span class='badge'>{ctx['role']}</span>"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — CRM</title><style>{CSS}</style></head>
<body><div class="topbar"><strong>CRM</strong>{org}<span class="sp"></span>
<form method="get" action="/search" style="display:flex;gap:6px">
<input name="q" placeholder="Search CRM…" aria-label="Global search" style="width:220px">
<button class="btn">Search</button></form>
<a href="/notifications" aria-label="Notifications">🔔{f' ({notif})' if notif else ''}</a>
<a href="/tasks/new">+ New</a>
<a href="/logout">{html.escape(ctx.get('email', ''))} ⏻</a></div>
<div class="layout"><nav class="sidebar" aria-label="Primary">
<h4>Workspace</h4>{links}</nav>
<main class="main">{body}</main></div></body></html>"""


def _form(body: bytes) -> dict:
    from urllib.parse import parse_qs

    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}


def login_page(error: str = "") -> HTMLResponse:
    msg = f"<div class='err' role='alert'>{html.escape(error)}</div>" if error else ""
    return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in — CRM</title>
<style>{CSS}</style></head><body style="display:flex;justify-content:center;padding-top:80px">
<div style="width:340px">{msg}<h2>Sign in</h2>
<form method="post" action="/login" class="grid">
<label>Email<input name="email" required></label>
<label>Password<input name="password" type="password" required></label>
<button class="btn">Sign in</button></form>
<p><a href="/signup">Create workspace</a> · <a href="/forgot">Forgot password?</a></p>
</div></body></html>""")


def _set_session(resp: HTMLResponse, user_id: str, org_id: str | None,
                 ua: str, ip: str) -> HTMLResponse:
    from crm.security import create_session

    resp.set_cookie("crm_session", create_session(user_id, org_id, ua, ip),
                    httponly=True, samesite="lax")
    return resp


def _signin_and_land(email: str, user_id: str, request: Request) -> HTMLResponse:
    from crm.services import authsvc as _auth

    org = _auth.default_org(user_id)
    resp = RedirectResponse("/" if org else "/settings", status_code=303)
    ua = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else ""
    return _set_session(resp, user_id, org["id"] if org else None, ua, ip)


def register_routes(api) -> None:
    from crm.security import revoke_all_sessions, revoke_session
    from crm.services import authsvc as _auth

    @api.get("/login", response_class=HTMLResponse)
    async def login_get():
        return login_page()

    @api.post("/login")
    async def login_post(request: Request):
        form = _form(await request.body())
        user = _auth.login(form.get("email", ""), form.get("password", ""))
        if not user:
            return login_page("Unknown email or wrong password.")
        return _signin_and_land(user["email"], user["id"], request)

    @api.get("/logout")
    async def logout(request: Request):
        from crm.security import read_session

        session = read_session(request.cookies.get("crm_session"))
        if session:
            revoke_session(session["session_id"], session["user_id"])
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie("crm_session")
        return resp

    @api.get("/signup", response_class=HTMLResponse)
    async def signup_get():
        return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign up — CRM</title>
<style>{CSS}</style></head><body style="display:flex;justify-content:center;padding-top:60px">
<div style="width:360px"><h2>Create your workspace</h2>
<form method="post" action="/signup" class="grid">
<label>Your name<input name="name" required></label>
<label>Email<input name="email" required></label>
<label>Password (10+ chars, mixed case, digit)<input name="password" type="password" required></label>
<label>Workspace name<input name="org_name" required></label>
<button class="btn">Create workspace</button></form>
<p><a href="/login">Back to sign in</a></p></div></body></html>""")

    @api.post("/signup")
    async def signup_post(request: Request):
        from crm.services.authsvc import AuthError

        form = _form(await request.body())
        try:
            ids = _auth.register(form.get("name", ""), form.get("email", ""),
                                 form.get("password", ""), form.get("org_name", "My workspace"))
        except AuthError as e:
            return HTMLResponse(f"Signup failed: {html.escape(str(e))} <a href='/signup'>Try again</a>",
                                status_code=400)
        return _signin_and_land(ids["user_id"] and form.get("email", ""), ids["user_id"], request)

    @api.get("/forgot", response_class=HTMLResponse)
    async def forgot_get(msg: str = ""):
        note = f"<div class='ok'>{html.escape(msg)}</div>" if msg else ""
        return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Reset — CRM</title><style>{CSS}</style></head>
<body style="display:flex;justify-content:center;padding-top:80px"><div style="width:340px">{note}
<h2>Reset password</h2><form method="post" action="/forgot" class="grid">
<label>Email<input name="email" required></label><button class="btn">Send reset token</button></form>
</div></body></html>""")

    @api.post("/forgot")
    async def forgot_post(request: Request):
        form = _form(await request.body())
        _auth.request_password_reset(form.get("email", ""))
        return await forgot_get("If the account exists, a reset token was emailed.")

    @api.get("/reset", response_class=HTMLResponse)
    async def reset_get(token: str = ""):
        return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>New password — CRM</title><style>{CSS}</style></head>
<body style="display:flex;justify-content:center;padding-top:80px"><div style="width:340px">
<h2>Choose a new password</h2><form method="post" action="/reset" class="grid">
<input type="hidden" name="token" value="{html.escape(token)}">
<label>New password<input name="new_password" type="password" required></label>
<button class="btn">Reset password</button></form></div></body></html>""")

    @api.post("/reset")
    async def reset_post(request: Request):
        from crm.services.authsvc import AuthError

        form = _form(await request.body())
        try:
            _auth.reset_password(form.get("token", ""), form.get("new_password", ""))
        except AuthError as e:
            return HTMLResponse(f"Reset failed: {html.escape(str(e))}", status_code=400)
        return RedirectResponse("/login", status_code=303)

    @api.get("/verify")
    async def verify(token: str = ""):
        ok = _auth.verify_email(token)
        return HTMLResponse(
            f"Email {'verified' if ok else 'verification failed'}. <a href='/login'>Sign in</a>")


def _ctx(request: Request) -> dict:
    from fastapi import HTTPException

    from crm import rbac as _rbac
    from crm.security import read_session

    session = read_session(request.cookies.get("crm_session"))
    if not session or not session.get("org_id"):
        raise HTTPException(303, headers={"Location": "/login"})
    role = _rbac.member_role(session["org_id"], session["user_id"])
    if not role:
        raise HTTPException(303, headers={"Location": "/login"})
    user = db.fetchone("SELECT id, email, name FROM users WHERE id = ?", (session["user_id"],))
    return {"session": session, "user_id": session["user_id"], "org_id": session["org_id"],
            "role": role, "email": user["email"], "name": user["name"]}


def _need(ctx: dict, permission: str) -> None:
    from fastapi import HTTPException

    from crm import rbac as _rbac

    try:
        _rbac.require(ctx["role"], permission)
    except _rbac.PermissionDenied as e:
        raise HTTPException(403, str(e))


def register_pages(api) -> None:
    from crm.services import activity as _act

    @api.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        ctx = _ctx(request)
        kpis = records.dashboard_kpis(ctx["org_id"])
        cards = "".join(
            f"<div class='card'><div class='v'>{kpis[k]}</div><div class='l'>{label}</div></div>"
            for k, label in [("contacts", "Contacts"), ("companies", "Companies"),
                             ("open_tasks", "Open tasks"), ("overdue_tasks", "Overdue tasks")])
        recent = "".join(
            f"<tr><td>{html.escape(a['created_at'][:16])}</td><td>{html.escape(a['type'])}</td>"
            f"<td>{html.escape(a['description'][:90])}</td></tr>" for a in kpis["recent_activity"])
        upcoming = "".join(
            f"<tr><td>{html.escape(t['title'])}</td><td>{t.get('due_date') or '—'}</td>"
            f"<td><span class='badge'>{t['priority']}</span></td></tr>" for t in kpis["upcoming_tasks"])
        return HTMLResponse(shell("Dashboard", "/", f"""
<h1>Dashboard</h1><div class="cards">{cards}</div>
<h3>Recent activity</h3><table><tbody>{recent or "<tr><td class='empty'>No activity yet.</td></tr>"}</tbody></table>
<h3>Upcoming tasks</h3><table><tbody>{upcoming or "<tr><td class='empty'>Nothing due.</td></tr>"}</tbody></table>
""", ctx))

    def _rows(items: list[dict], cols: list[str], link: str) -> str:
        if not items:
            return "<tr><td class='empty' colspan='10'>Nothing here yet.</td></tr>"
        return "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '') or ''))}</td>" for c in cols)
            + f"<td><a href='{link}/{r['id']}'>Open</a></td></tr>" for r in items)

    @api.get("/contacts", response_class=HTMLResponse)
    async def contacts_page(request: Request, q: str = ""):
        ctx = _ctx(request)
        _need(ctx, "contacts.read")
        rows, total = records.list_contacts(ctx["org_id"], {"q": q or None})
        body = f"""<h1>Contacts ({total})</h1>
<form method="get" action="/contacts"><input name="q" value="{html.escape(q)}" placeholder="Search name or email"></form>
<p><a class="btn" href="/contacts/new">+ New contact</a></p>
<table><thead><tr><th>Name</th><th>Email</th><th>Stage</th><th></th></tr></thead><tbody>
{''.join(f"<tr><td>{html.escape(r['first_name'])} {html.escape(r['last_name'])}</td><td>{html.escape(r.get('email') or '')}</td><td><span class='badge'>{r['lifecycle_stage']}</span></td><td><a href='/contacts/{r['id']}'>Open</a></td></tr>" for r in rows) or "<tr><td class='empty' colspan='10'>No contacts yet. Add your first contact to start building your CRM.</td></tr>"}
</tbody></table>"""
        return HTMLResponse(shell("Contacts", "/contacts", body, ctx))

    @api.get("/contacts/new", response_class=HTMLResponse)
    async def contact_new(request: Request):
        ctx = _ctx(request)
        _need(ctx, "contacts.create")
        return HTMLResponse(shell("New contact", "/contacts", """
<h1>New contact</h1><form method="post" action="/contacts" class="grid">
<label>First name<input name="first_name"></label>
<label>Last name<input name="last_name"></label>
<label>Email<input name="email"></label>
<label>Phone<input name="phone"></label>
<label>Job title<input name="job_title"></label>
<label>Lifecycle stage<select name="lifecycle_stage">
<option>lead</option><option>prospect</option><option>customer</option><option>churned</option></select></label>
<button class="btn">Create contact</button></form>""", ctx))

    @api.post("/contacts")
    async def contact_create(request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "contacts.create")
        form = _form(await request.body())
        try:
            c = records.create_contact(ctx["org_id"], ctx["user_id"], form,
                                       request.client.host if request.client else "", "")
        except ValueError as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        return RedirectResponse(f"/contacts/{c['id']}", status_code=303)

    @api.get("/contacts/{contact_id}", response_class=HTMLResponse)
    async def contact_detail(contact_id: str, request: Request):
        ctx = _ctx(request)
        _need(ctx, "contacts.read")
        c = records.contact_detail(ctx["org_id"], contact_id)
        if not c:
            return HTMLResponse("Not found.", status_code=404)
        notes = "".join(f"<li>{html.escape(n['body'][:200])}</li>" for n in c["notes"])
        tasks = "".join(f"<li>{html.escape(t['title'])} — {t['status']}</li>" for t in c["tasks"])
        timeline = "".join(
            f"<li>{html.escape(a['created_at'][:16])} · {html.escape(a['type'])} — {html.escape(a['description'][:120])}</li>"
            for a in c["timeline"])
        return HTMLResponse(shell(f"{c['first_name']} {c['last_name']}", "/contacts", f"""
<h1>{html.escape(c['first_name'])} {html.escape(c['last_name'])}</h1>
<p>{html.escape(c.get('email') or '')} · {html.escape(c.get('job_title') or '')} ·
<span class='badge'>{c['lifecycle_stage']}</span> {', '.join(html.escape(t) for t in c['tags'])}</p>
<p><a class="btn ghost" href="/contacts/{contact_id}/edit">Edit</a>
<form method="post" action="/contacts/{contact_id}/delete" style="display:inline"
onsubmit="return confirm('Delete this contact?')"><button class="btn danger">Delete</button></form></p>
<h3>Notes</h3><ul>{notes or '<li class="empty">No notes.</li>'}</ul>
<form method="post" action="/notes" class="grid">
<input type="hidden" name="entity_type" value="contact">
<input type="hidden" name="entity_id" value="{contact_id}">
<textarea name="body" placeholder="Add a note…" required></textarea>
<button class="btn">Add note</button></form>
<h3>Tasks</h3><ul>{tasks or '<li class="empty">No tasks.</li>'}</ul>
<h3>Timeline</h3><ul>{timeline or '<li class="empty">No activity.</li>'}</ul>""", ctx))

    @api.get("/contacts/{contact_id}/edit", response_class=HTMLResponse)
    async def contact_edit(contact_id: str, request: Request):
        ctx = _ctx(request)
        _need(ctx, "contacts.update")
        c = records.contact_detail(ctx["org_id"], contact_id)
        if not c:
            return HTMLResponse("Not found.", status_code=404)
        return HTMLResponse(shell("Edit contact", "/contacts", f"""
<h1>Edit contact</h1><form method="post" action="/contacts/{contact_id}" class="grid">
<label>First name<input name="first_name" value="{html.escape(c['first_name'])}"></label>
<label>Last name<input name="last_name" value="{html.escape(c['last_name'])}"></label>
<label>Email<input name="email" value="{html.escape(c.get('email') or '')}"></label>
<label>Phone<input name="phone" value="{html.escape(c.get('phone') or '')}"></label>
<label>Job title<input name="job_title" value="{html.escape(c.get('job_title') or '')}"></label>
<button class="btn">Save</button></form>""", ctx))

    @api.post("/contacts/{contact_id}")
    async def contact_save(contact_id: str, request: Request):
        ctx = _ctx(request)
        _need(ctx, "contacts.update")
        form = _form(await request.body())
        try:
            updated = records.update_contact(ctx["org_id"], contact_id, ctx["user_id"], form, "", "")
        except ValueError as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        if not updated:
            return HTMLResponse("Not found.", status_code=404)
        from fastapi.responses import RedirectResponse

        return RedirectResponse(f"/contacts/{contact_id}", status_code=303)

    @api.post("/contacts/{contact_id}/delete")
    async def contact_delete(contact_id: str, request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "contacts.delete")
        records.delete_contact(ctx["org_id"], contact_id, ctx["user_id"], "", "")
        return RedirectResponse("/contacts", status_code=303)

    @api.get("/companies", response_class=HTMLResponse)
    async def companies_page(request: Request, q: str = ""):
        ctx = _ctx(request)
        _need(ctx, "companies.read")
        rows, total = records.list_companies(ctx["org_id"], {"q": q or None})
        items = "".join(
            f"<tr><td>{html.escape(r['name'])}</td><td>{html.escape(r.get('industry') or '')}</td>"
            f"<td><a href='/companies/{r['id']}'>Open</a></td></tr>" for r in rows)
        return HTMLResponse(shell("Companies", "/companies", f"""
<h1>Companies ({total})</h1>
<form method="get" action="/companies"><input name="q" value="{html.escape(q)}" placeholder="Search companies"></form>
<p><a class="btn" href="/companies/new">+ New company</a></p>
<table><thead><tr><th>Name</th><th>Industry</th><th></th></tr></thead><tbody>
{items or "<tr><td class='empty' colspan='10'>No companies yet.</td></tr>"}</tbody></table>""", ctx))

    @api.get("/companies/new", response_class=HTMLResponse)
    async def company_new(request: Request):
        ctx = _ctx(request)
        _need(ctx, "companies.create")
        return HTMLResponse(shell("New company", "/companies", """
<h1>New company</h1><form method="post" action="/companies" class="grid">
<label>Name<input name="name" required></label>
<label>Industry<input name="industry"></label>
<label>Website<input name="website"></label>
<label>Email<input name="email"></label>
<button class="btn">Create company</button></form>""", ctx))

    @api.post("/companies")
    async def company_create(request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "companies.create")
        form = _form(await request.body())
        try:
            c = records.create_company(ctx["org_id"], ctx["user_id"], form, "", "")
        except ValueError as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        return RedirectResponse(f"/companies/{c['id']}", status_code=303)

    @api.get("/companies/{company_id}", response_class=HTMLResponse)
    async def company_detail(company_id: str, request: Request):
        ctx = _ctx(request)
        _need(ctx, "companies.read")
        c = records.company_detail(ctx["org_id"], company_id)
        if not c:
            return HTMLResponse("Not found.", status_code=404)
        contacts = "".join(
            f"<li><a href='/contacts/{x['id']}'>{html.escape(x['first_name'])} {html.escape(x['last_name'])}</a></li>"
            for x in c["contacts"])
        notes = "".join(f"<li>{html.escape(n['body'][:200])}</li>" for n in c["notes"])
        return HTMLResponse(shell(c["name"], "/companies", f"""
<h1>{html.escape(c['name'])}</h1>
<p>{html.escape(c.get('industry') or '')} · {html.escape(c.get('website') or '')} · {html.escape(c.get('email') or '')}</p>
<form method="post" action="/companies/{company_id}/delete" style="display:inline"
onsubmit="return confirm('Delete this company?')"><button class="btn danger">Delete</button></form>
<h3>Contacts</h3><ul>{contacts or '<li class="empty">No contacts linked.</li>'}</ul>
<h3>Notes</h3><ul>{notes or '<li class="empty">No notes.</li>'}</ul>
<form method="post" action="/notes" class="grid">
<input type="hidden" name="entity_type" value="company">
<input type="hidden" name="entity_id" value="{company_id}">
<textarea name="body" placeholder="Add a note…" required></textarea>
<button class="btn">Add note</button></form>""", ctx))

    @api.post("/companies/{company_id}/delete")
    async def company_delete(company_id: str, request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "companies.delete")
        try:
            ok = records.delete_company(ctx["org_id"], company_id, ctx["user_id"], "", "")
        except ValueError as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        if not ok:
            return HTMLResponse("Not found.", status_code=404)
        return RedirectResponse("/companies", status_code=303)

    @api.post("/notes")
    async def note_create(request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "notes.create")
        form = _form(await request.body())
        try:
            records.add_note(ctx["org_id"], ctx["user_id"], form.get("entity_type", ""),
                             form.get("entity_id", ""), form.get("body", ""), "", "")
        except ValueError as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        back = {"contact": "/contacts/", "company": "/companies/"}.get(form.get("entity_type"), "/")
        return RedirectResponse(f"{back}{form.get('entity_id', '')}", status_code=303)

    @api.get("/tasks", response_class=HTMLResponse)
    async def tasks_page(request: Request, status: str = ""):
        ctx = _ctx(request)
        _need(ctx, "tasks.read")
        rows, _ = records.list_tasks(ctx["org_id"], {"status": status or None})
        items = "".join(
            f"<tr><td>{html.escape(t['title'])}</td><td>{t.get('due_date') or '—'}</td>"
            f"<td><span class='badge'>{t['priority']}</span></td><td>{t['status']}</td>"
            f"<td><form method='post' action='/tasks/{t['id']}/complete' style='display:inline'>"
            f"<button class='btn ghost'>Done</button></form></td></tr>" for t in rows)
        return HTMLResponse(shell("Tasks", "/tasks", f"""
<h1>Tasks</h1>
<p><a class="btn" href="/tasks/new">+ New task</a>
<a class="btn ghost" href="/tasks?status=todo">Open</a>
<a class="btn ghost" href="/tasks">All</a></p>
<table><thead><tr><th>Title</th><th>Due</th><th>Priority</th><th>Status</th><th></th></tr></thead>
<tbody>{items or "<tr><td class='empty' colspan='10'>No tasks. Enjoy the calm.</td></tr>"}</tbody></table>""", ctx))

    @api.get("/tasks/new", response_class=HTMLResponse)
    async def task_new(request: Request):
        ctx = _ctx(request)
        _need(ctx, "tasks.create")
        return HTMLResponse(shell("New task", "/tasks", """
<h1>New task</h1><form method="post" action="/tasks" class="grid">
<label>Title<input name="title" required></label>
<label>Description<textarea name="description"></textarea></label>
<label>Due date<input name="due_date" type="date"></label>
<label>Priority<select name="priority"><option>low</option><option selected>medium</option>
<option>high</option><option>urgent</option></select></label>
<button class="btn">Create task</button></form>""", ctx))

    @api.post("/tasks")
    async def task_create(request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "tasks.create")
        form = _form(await request.body())
        records.create_task(ctx["org_id"], ctx["user_id"],
                            {"title": form.get("title", ""), "description": form.get("description", ""),
                             "due_date": form.get("due_date") or None,
                             "priority": form.get("priority", "medium")}, "", "")
        return RedirectResponse("/tasks", status_code=303)

    @api.post("/tasks/{task_id}/complete")
    async def task_complete(task_id: str, request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "tasks.update")
        records.complete_task(ctx["org_id"], task_id, ctx["user_id"], "", "")
        return RedirectResponse("/tasks", status_code=303)

    @api.get("/activities", response_class=HTMLResponse)
    async def activities_page(request: Request):
        ctx = _ctx(request)
        _need(ctx, "activities.read")
        rows = db.fetchall("SELECT * FROM activities WHERE org_id = ? ORDER BY created_at DESC LIMIT 100",
                           (ctx["org_id"],))
        items = "".join(
            f"<tr><td>{html.escape(a['created_at'][:16])}</td><td>{html.escape(a['type'])}</td>"
            f"<td>{html.escape(a['description'][:140])}</td></tr>" for a in rows)
        return HTMLResponse(shell("Activities", "/activities",
                                  f"<h1>Activities</h1><table><tbody>{items or '<tr><td class=empty>No activity yet.</td></tr>'}</tbody></table>", ctx))

    @api.get("/search", response_class=HTMLResponse)
    async def search_page(request: Request, q: str = ""):
        from crm.services import records as _rec

        ctx = _ctx(request)
        res = _rec.global_search(ctx["org_id"], q) if q.strip() else {}
        def _sec(title: str, items: list[dict], link: str, label: str) -> str:
            lis = "".join(f"<li><a href='/{link}/{i['id']}'>{html.escape(i[label])}</a></li>" for i in items)
            return f"<h3>{title} ({len(items)})</h3><ul>{lis or '<li class=empty>None.</li>'}</ul>"
        return HTMLResponse(shell("Search", "/search",
                                  f"<h1>Results for “{html.escape(q)}”</h1>"
                                  + _sec("Contacts", res.get("contacts", []), "contacts", "email")
                                  + _sec("Companies", res.get("companies", []), "companies", "name")
                                  + _sec("Tasks", res.get("tasks", []), "tasks", "title"), ctx))

    @api.get("/notifications", response_class=HTMLResponse)
    async def notifications_page(request: Request):
        ctx = _ctx(request)
        rows = db.fetchall(
            "SELECT * FROM notifications WHERE org_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 50",
            (ctx["org_id"], ctx["user_id"]))
        items = "".join(
            f"<tr><td>{html.escape(n['title'])}</td><td>{html.escape(n['created_at'][:16])}</td>"
            f"<td>{'read' if n['read_at'] else '<strong>unread</strong>'}</td></tr>" for n in rows)
        return HTMLResponse(shell("Notifications", "/notifications", f"""
<h1>Notifications</h1>
<form method="post" action="/notifications/read-all"><button class="btn ghost">Mark all read</button></form>
<table><tbody>{items or "<tr><td class='empty'>All caught up.</td></tr>"}</tbody></table>""", ctx))

    @api.post("/notifications/read-all")
    async def notifications_read_all(request: Request):
        from datetime import datetime, timezone

        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        db.execute("UPDATE notifications SET read_at = ? WHERE org_id = ? AND user_id = ?",
                   (datetime.now(timezone.utc).isoformat(), ctx["org_id"], ctx["user_id"]))
        return RedirectResponse("/notifications", status_code=303)

    @api.get("/team", response_class=HTMLResponse)
    async def team_page(request: Request):
        ctx = _ctx(request)
        _need(ctx, "users.read")
        members = orgsvc.members(ctx["org_id"])
        rows = "".join(
            f"<tr><td>{html.escape(m['name'])}</td><td>{html.escape(m['email'])}</td>"
            f"<td><span class='badge'>{m['role']}</span></td></tr>" for m in members)
        invite = """<h3>Invite member</h3><form method="post" action="/team/invite" class="grid">
<label>Email<input name="email" required></label>
<label>Role<select name="role"><option>sales</option><option>manager</option>
<option>admin</option><option>viewer</option></select></label>
<button class="btn">Send invite</button></form>""" if rbac.can(ctx["role"], "users.invite") else ""
        return HTMLResponse(shell("Team", "/team",
                                  f"<h1>Team</h1><table><thead><tr><th>Name</th><th>Email</th><th>Role</th></tr></thead>"
                                  f"<tbody>{rows}</tbody></table>{invite}", ctx))

    @api.post("/team/invite")
    async def team_invite(request: Request):
        ctx = _ctx(request)
        _need(ctx, "users.invite")
        form = _form(await request.body())
        from crm.services.authsvc import AuthError, invite

        try:
            invite(ctx["org_id"], form.get("email", ""), form.get("role", "sales"), ctx["user_id"])
        except (AuthError, ValueError) as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/team", status_code=303)

    @api.get("/audit", response_class=HTMLResponse)
    async def audit_page(request: Request):
        ctx = _ctx(request)
        _need(ctx, "audit.read")
        rows = db.fetchall("SELECT * FROM audit_logs WHERE org_id = ? ORDER BY created_at DESC LIMIT 100",
                           (ctx["org_id"],))
        items = "".join(
            f"<tr><td>{html.escape(a['created_at'][:16])}</td><td>{html.escape(a['action'])}</td>"
            f"<td>{html.escape(a['entity_type'])}/{html.escape(a['entity_id'][:8])}</td></tr>"
            for a in rows)
        return HTMLResponse(shell("Audit log", "/audit",
                                  f"<h1>Audit log</h1><table><tbody>{items or '<tr><td class=empty>No events.</td></tr>'}</tbody></table>", ctx))

    @api.get("/reports", response_class=HTMLResponse)
    async def reports_page(request: Request):
        ctx = _ctx(request)
        _need(ctx, "reports.read")
        kpis = records.dashboard_kpis(ctx["org_id"])
        stages = db.fetchall(
            "SELECT lifecycle_stage AS stage, COUNT(*) AS n FROM contacts WHERE org_id = ?"
            " AND deleted_at IS NULL GROUP BY stage", (ctx["org_id"],))
        total = sum(s["n"] for s in stages) or 1
        bars = "".join(
            f"<tr><td>{html.escape(s['stage'])}</td><td style='width:50%'><div class='bar'>"
            f"<i style='width:{100 * s['n'] // total}%'></i></div></td><td>{s['n']}</td></tr>"
            for s in stages)
        return HTMLResponse(shell("Reports", "/reports", f"""
<h1>Reports</h1>
<div class="cards">
<div class='card'><div class='v'>{kpis['contacts']}</div><div class='l'>Contacts</div></div>
<div class='card'><div class='v'>{kpis['companies']}</div><div class='l'>Companies</div></div>
<div class='card'><div class='v'>{kpis['open_tasks']}</div><div class='l'>Open tasks</div></div>
<div class='card'><div class='v'>{kpis['overdue_tasks']}</div><div class='l'>Overdue tasks</div></div>
</div>
<h3>Contacts by lifecycle stage</h3>
<table><tbody>{bars or "<tr><td class='empty'>No data.</td></tr>"}</tbody></table>""", ctx))

    @api.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        ctx = _ctx(request)
        org = orgsvc.get_org(ctx["org_id"])
        editable = rbac.can(ctx["role"], "organization.update")
        ro = "" if editable else "disabled"
        return HTMLResponse(shell("Settings", "/settings", f"""
<h1>Settings</h1>
<h3>Profile</h3>
<form method="post" action="/settings/password" class="grid">
<label>Current password<input name="current_password" type="password" required></label>
<label>New password<input name="new_password" type="password" required></label>
<button class="btn">Change password</button></form>
<h3>Organization</h3>
<form method="post" action="/settings/org" class="grid">
<label>Name<input name="name" value="{html.escape(org['name'])}" {ro}></label>
<label>Currency<input name="currency" value="{html.escape(org['currency'])}" {ro}></label>
<label>Timezone<input name="timezone" value="{html.escape(org['timezone'])}" {ro}></label>
<button class="btn" {ro}>Save organization</button></form>
<p><a class="btn ghost" href="/logout">Sign out everywhere (this device too)</a></p>
""", ctx))

    @api.post("/settings/password")
    async def settings_password(request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        form = _form(await request.body())
        from crm.services.authsvc import AuthError, change_password

        try:
            change_password(ctx["user_id"], form.get("current_password", ""),
                            form.get("new_password", ""))
        except AuthError as e:
            return HTMLResponse(f"<div class='err'>{html.escape(str(e))}</div>", status_code=400)
        return RedirectResponse("/settings", status_code=303)

    @api.post("/settings/org")
    async def settings_org(request: Request):
        from fastapi.responses import RedirectResponse

        ctx = _ctx(request)
        _need(ctx, "organization.update")
        form = _form(await request.body())
        orgsvc.update_org(ctx["org_id"], ctx["user_id"], "", "", name=form.get("name"),
                          currency=form.get("currency"), timezone=form.get("timezone"),
                          locale=form.get("locale"))
        return RedirectResponse("/settings", status_code=303)

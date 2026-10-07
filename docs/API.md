# API

Machine spec: `GET /api/openapi.json` (or `/docs` in browser).
All routes below require auth except register/login/forgot/reset/verify.

## Conventions

- Errors: `{code, message, field_errors, request_id}` + matching HTTP status.
- Lists: `{data, total, page, page_size}` (page_size capped at 100).
- Auth: `crm_session` cookie. Org always from session.
- Health: `GET /health` → `{"status":"ok"}`.

## Reference

```text
POST /api/auth/register {name,email,password,org_name} -> 201 {user_id,org_id}
POST /api/auth/login {email,password} -> {user_id,org_id} (sets cookie)
POST /api/auth/logout | GET /api/auth/me
POST /api/auth/switch-org/{org_id}
POST /api/auth/change-password | POST /api/auth/forgot | POST /api/auth/reset
POST /api/auth/verify?token= | POST /api/auth/resend-verification
GET  /api/auth/sessions | POST /api/auth/sessions/{id}/revoke | POST /api/auth/logout-all

GET  /api/org | PATCH /api/org
GET  /api/members | POST /api/members/invite | POST /api/members/accept
PATCH /api/members/{user_id} (role) | DELETE /api/members/{user_id}
GET  /api/teams | POST /api/teams

GET  /api/contacts?q=&status=&stage=&owner_id=&company_id=&tag=&page=&sort=&direction=
POST /api/contacts | GET,PATCH /api/contacts/{id} | DELETE (soft)
POST /api/contacts/{id}/archive | POST /api/contacts/{id}/restore

GET  /api/companies?q=&status=&industry= | POST /api/companies
GET,PATCH /api/companies/{id} | DELETE (blocked with active contacts)

POST /api/notes {entity_type,entity_id,body}
GET  /api/tasks?status=&priority=&assignee_id=&overdue=true | POST /api/tasks
POST /api/tasks/{id}/status {status}
GET  /api/activities
GET  /api/search?q=            -> {contacts,companies,tasks}
GET  /api/dashboard            -> KPIs + recent activity + upcoming tasks
GET  /api/audit                 (audit.read only)
GET  /api/notifications | POST /api/notifications/read-all
```

## Permissions per route

Each route lists its permission, e.g. contacts.*, users.invite,
audit.read — full matrix in `crm/rbac.py:ROLE_PERMISSIONS`. Viewer reads only.

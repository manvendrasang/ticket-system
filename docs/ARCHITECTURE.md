# Architecture

Single Python service (FastAPI) + SQLite + server-rendered UI. No build step,
no JS framework, no ORM — a small repository layer over `sqlite3` keeps every
query visible and Postgres-portable.

```text
browser ──► crm/server.py (FastAPI app)
               ├── crm/api.py        JSON API (/api/…), auth deps per route
               └── crm/web.py        HTML pages (same deps, redirects to /login)
                        │
crm/services/ ─┤  authsvc · orgsvc · records · activity(audit/notify) · emailing
                        │
crm/ ──────────┤  db.py (connections, migrations) · rbac.py · security.py · models.py
                        │
               data/crm.db (SQLite WAL) — migrations in crm/migrations/
```

## Request lifecycle

1. Cookie `crm_session` → `security.read_session` (DB row, idle timeout).
2. Org resolved **from the session**, never from client input.
3. `rbac.require(role, permission)` per route (API: 403 JSON, pages: 403).
4. Service validates input, runs one logical transaction, writes audit + activity.
5. Errors return `{code, message, field_errors, request_id}` (never stack traces).

## Key decisions (see PROJECT_AUDIT.md)

- SQLite over Postgres: no server available on target hosts; SQL avoids
  SQLite-only functions so a Postgres move is a driver swap + DDL pass.
- Server-rendered HTML over React SPA: zero build, works without JS for
  forms; `fetch` used only for search/palette-style enhancements.
- No ORM: 30-table schema is fully visible in `001_initial.sql`; adding
  SQLAlchemy would hide the tenant-scoping that must stay obvious.
- Monolith over services: single deployable, SQLite can't be shared safely
  across processes for writes beyond this scale (documented limit).

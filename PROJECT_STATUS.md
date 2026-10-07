# Project status (master-prompt §83)

## Completed (Phase 0–1: audit + foundation)

- [x] Repository audit (`PROJECT_AUDIT.md`)
- [x] Architecture, database, API, security, testing, deployment docs
- [x] SQLite schema + migration runner (`001_initial.sql`)
- [x] Auth: register+org, login/logout, sessions list/revoke/logout-all,
      change/reset/forgot password, email verify/resend, invites/accept
- [x] Orgs/members/roles(5)/teams/invites, last-owner protection
- [x] RBAC matrix enforced server-side on every route
- [x] Contacts + companies CRUD, archive/restore/soft-delete, tags,
      duplicate detection, delete-blocked-with-contacts
- [x] Notes, tasks (+notifications on assign), activities timeline
- [x] Global search, dashboard KPIs, reports page, notifications center
- [x] Audit log (insert-only, actor/IP/UA)
- [x] Server-rendered UI: shell, auth pages, dashboard, contacts/companies/
      tasks/activities/search/team/audit/reports/settings/notifications
- [x] 21 tests green; demo seed (Acme Corporation)

## In progress

- [ ] Phase 2 kickoff: leads + conversion (next)

## Not started (spec order)

- Leads, pipelines/Kanban, deals, calendar/meetings, files, custom fields,
  saved views, import/export, settings subsections, rate limiting, CSRF,
  2FA, ruff/mypy/CI, Dockerfile, Postgres pass.

## Known issues / debt

- UI is server-rendered, not React (conscious deviation, documented).
- `HttpOnly` cookies without `Secure`; no CSRF tokens yet.
- Money stored as REAL (fine for phase 1; decimal pass with Postgres).
- No lockfile; dependency versions unpinned.
- Old ticket-system code fully removed; `models/` weights remain on disk
  (gitignored, unused by the CRM).

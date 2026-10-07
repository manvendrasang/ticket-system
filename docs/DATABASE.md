# Database

File: `data/crm.db` (`DATABASE_PATH`). Migrations in `crm/migrations/`,
tracked in `schema_migrations`. Add a new `NNN_name.sql` for every change —
never edit a landed migration; never hand-edit the file.

## Conventions

- TEXT uuid PKs (`uuid4().hex`), INTEGER 0/1 flags, TEXT ISO-8601 timestamps.
- Every tenant row has `org_id` + index; FKs with explicit `ON DELETE` rules.
- Soft delete (`deleted_at`, `deleted_by`) for contacts/companies; hard delete
  only for tokens and expired rows.
- Money: REAL in SQLite; use `decimal` semantics on the Postgres pass
  (amounts are informational in phase 1 — no ledger math yet).

## Tables (001_initial)

`organizations, users, organization_members, teams, team_members, invites,
password_resets, email_verifications, sessions, contacts, companies, tags,
contact_tags, company_tags, notes, tasks, activities, notifications, audit_logs`

## Index strategy

org_id on every tenant table; email lookups; owner/status/updated filters;
`(entity_type, entity_id)` for notes/activities; `due_date` for tasks.

## Integrity rules (all server-side)

- UNIQUE: `users.email`, `(org_id,user_id)`, `(org_id,name)` on tags/companies
  (case-insensitive for companies), invite/reset token hashes.
- Duplicate contact email per org rejected with the conflicting id.
- Company with active contacts cannot be deleted.
- Last owner cannot be demoted or removed.
- Audit rows are insert-only (no update/delete code paths exist).

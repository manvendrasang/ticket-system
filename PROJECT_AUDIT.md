# PROJECT_AUDIT.md — repository audit (master-prompt Phase 0)

Date: 2026-10-07. Scope: whole repo excluding `myenv/`, `models/` weights.

## 1. Current architecture

Python monolith, server-rendered HTML over FastAPI, no JS framework:

| Area | Reality |
|---|---|
| Language | Python 3.11 |
| Backend | FastAPI 0.142.2 + uvicorn 0.54.0 (two apps: `app/api.py` :8001 intake, `dashboard/app.py` :8000 UI) |
| Frontend | Server-rendered HTML strings + vanilla JS `fetch` (no React/TS/Tailwind) |
| Database | SQLite via stdlib `sqlite3` (`app/db.py`, WAL mode, per-operation connections). No ORM, no migrations |
| Auth | Custom: pbkdf2 passwords, HMAC cookie sessions + heartbeat idle timeout, Basic (legacy) + Bearer tokens for API |
| AI | Vendored TinyLlama-1.1B + QLoRA adapter, lazy load, keyword fallback |
| Tests | pytest, 87 tests (incl. API/roles/features), all green |
| Package manager | pip + `requirements.txt` / `training/requirements-train.txt` |
| Env config | `.env` (gitignored) + `.env.example`; partial `app/config.py` (not wired everywhere) |
| Logging | stdlib logging + JSONL audit; Prometheus-style `/metrics` hand-rolled |
| Deployment | None (no Dockerfile, compose, CI). No Postgres, no Docker daemon on this host |

## 2. Existing functionality (working, tested)

Ticket intake (API + 4 channels), resolver pipeline with guardrails, refunds/store-credit/exchange tools, SQLite queue + worker + DLQ, human approvals, roles (customer/sysadmin), PII masking, retention purge, dashboard + customer portal, fine-tune pipeline (0.929 eval).

## 3. Broken / incomplete (verified)

- `app/config.py` exists but most modules read `os.environ` directly — two config sources.
- `app/tools/registry.py` `TOOL_DEFINITIONS` unused; `app/agents/prompts.py` dead code.
- Dashboard approve/reject calls same-origin routes (fixed); API tokens only in-memory env list.
- No rate limiting, no CSRF tokens on cookie-POST forms, no password reset, no email verification, no pagination metadata standard, no migrations story.

## 4. Technical debt

- HTML built as Python f-strings (no templates); dashboard file is ~800 lines.
- `data/*.json` fixtures double as lookup DB with no integrity layer.
- Audit JSONL can interleave under multi-process writes (tolerant reader mitigates).
- No lint/typecheck config (ruff/mypy absent).

## 5. Dependency risks

- `torch` (~4 GB with CUDA wheels) dominates install size; pinned nowhere (unpinned ranges).
- `huggingface_hub`, `peft`, `trl`, `bitsandbytes` unpinned; training-only but in one env.
- No lockfile (`pip freeze` never recorded).

## 6. Security risks (to address in CRM build)

- `SECRET_KEY` defaults to insecure value with only a log warning.
- Cookie sessions lack `Secure` flag; no CSRF protection on form POSTs.
- No rate limiting on login/signup; no account lockout.
- SQLite file readable by any local user; no encryption at rest.
- PII (emails) in plaintext logs/audit JSONL.

## 7. CRM gap analysis (spec §9 entities vs repo)

| Spec entity | Repo status |
|---|---|
| Organization/Member/Role/Permission/Team | **Missing** (single-tenant; roles are global customer/sysadmin) |
| Contact/Company/Lead/Deal/Pipeline/Stages | **Missing** (only support-ticket domain) |
| Activity/Task/Meeting/Call/Note/Tag/Attachment/Comment | **Missing** |
| Notification/CustomField/SavedView/Report/Import/ExportJob | **Missing** |
| AuditLog | Partial (ticket audit events, no actor/IP/user-agent, mutable JSONL) |
| Dashboard/Reports | Partial (ticket stats only, no charts) |
| Notifications center | **Missing** |

## 8. Stack decision drivers

- Spec §4 suggests React+TS / Postgres+Prisma. Host has **Node 26** but **no Postgres, no Docker**.
- Existing team velocity, tests, and deployment reality favor **Python/FastAPI + SQLite (Postgres-ready repository layer)** with server-rendered UI progressively enhanced.
- React SPA would orphan 87 passing tests and the entire support pipeline; a full rewrite doubles risk with no infra to host Postgres.
- Recommendation: keep Python/FastAPI/SQLite core, add repository abstraction with Postgres-compatible SQL, keep vanilla-JS UI, add Docker files as docs-ready artifacts. Awaiting product decision (see questions).

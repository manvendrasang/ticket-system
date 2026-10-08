THIS REPO IS NOW CLOSED AND BEING MERGED UNDER BigCRM REPO




# ShopWave CRM

Production-grade CRM foundation: multi-tenant organizations, RBAC (5 roles),
contacts, companies, tasks, notes, tags, activities, notifications, audit
log, global search, dashboard, reports. Local-first: Python/FastAPI +
SQLite, server-rendered UI, no build step.

> Previous ticket-support system was fully replaced per product decision;
> reusable infra (auth sessions, SQLite patterns) was carried over.
> Audit of the old system: `PROJECT_AUDIT.md`.

## Quickstart

```bash
python3.11 -m venv myenv && myenv/bin/pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY
myenv/bin/python scripts/seed_demo.py   # optional: Acme demo org
myenv/bin/python -m uvicorn crm.server:app --port 8000
```

Demo login: `ava@acme.example` / `AcmeDemo123`. API docs: `/docs`.

## Test

```bash
myenv/bin/python -m pytest tests/ -q   # 21 tests, ~2s, isolated temp DB
```

## Docs

`docs/ARCHITECTURE.md` · `docs/DATABASE.md` · `docs/API.md` ·
`docs/SECURITY.md` · `docs/TESTING.md` · `docs/DEPLOYMENT.md` ·
`PROJECT_STATUS.md` (phases, debt, roadmap).

## License

Copyright © 2026 Manvendra Sang. All rights reserved. Proprietary —
no permission is granted to use, copy, modify, or distribute without
prior written permission from the copyright holder.

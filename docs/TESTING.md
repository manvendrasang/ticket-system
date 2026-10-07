# Testing

```bash
myenv/bin/python -m pytest tests/ -q
```

Isolated temp SQLite DB per session (`tests/__init__.py` sets
`DATABASE_PATH` before any `crm` import). No network, no model.

| File | Type | Covers |
|---|---|---|
| `test_rbac.py` | unit | permission matrix, password rules |
| `test_auth.py` | integration | register/login/logout, reset, sessions, invites, tenant isolation, role rejection |
| `test_records.py` | integration | contact/company CRUD, duplicates, delete-block, notes/tasks/notifications, search, dashboard, audit |
| `test_web.py` | e2e (HTTP) | signup→dashboard, contact flow, all pages render, anonymous redirects |

21 tests, ~2s. Checkpoints per master prompt §84: no lint/type tooling
configured yet (ruff/mypy planned); tests + manual smoke per module so far.

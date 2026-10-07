# Deployment

## Local

```bash
python3.11 -m venv myenv && myenv/bin/pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY
myenv/bin/python scripts/seed_demo.py   # optional demo data
myenv/bin/python -m uvicorn crm.server:app --port 8000
```

Migrations run automatically at startup (`crm/db.py:migrate`).

## Production checklist (not done)

- Postgres (swap `crm/db.py` connect + DDL pass; SQL is written compatibly)
- `SECRET_KEY` from a secret manager; `Secure` cookies behind HTTPS
- Reverse proxy (TLS termination), systemd/docker unit
- Backups of the SQLite file (or Postgres PITR)
- Rate limiting + security headers middleware
- Dockerfile + compose + CI (spec phases; host has no Docker daemon)

## Environment variables

See `.env.example`: `DATABASE_PATH, SECRET_KEY, APP_URL, LOG_LEVEL,
EMAIL_PROVIDER, EMAIL_FROM`.

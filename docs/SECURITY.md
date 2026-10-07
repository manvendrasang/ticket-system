# Security

## Implemented

- Passwords: pbkdf2-sha256/200k, 10+ chars with complexity rules, verified
  server-side on register/change/reset/accept.
- Sessions: 256-bit DB-backed tokens, httponly + SameSite=Lax cookies,
  per-device list/revoke, revoke-all, 30-day absolute + 1h idle expiry.
- Reset/verify/invite: single-use hashed tokens with expirations; reset
  revokes all sessions; forgot is enumeration-safe.
- Tenant isolation: org_id from session only; every tenant query scoped;
  cross-org access returns 404 (no existence leak); covered by tests.
- RBAC on every route (API 403 JSON, pages 403); last-owner protection.
- Validation: Pydantic on API, manual checks on HTML forms; error bodies
  never include traces or secrets.
- Audit: backend-generated, insert-only, includes actor/IP/user-agent.
- PII: plaintext emails in DB (SQLite file perms are the boundary — see risks).

## Known risks (not yet mitigated)

1. `SECRET_KEY` default is insecure — set it in production (warns in logs).
2. No rate limiting on login/signup/reset (planned: middleware + tests).
3. No CSRF tokens on cookie-POST HTML forms (SameSite=Lax only).
4. Cookies lack `Secure` flag (needs HTTPS deployment).
5. No 2FA (schema-ready: add `totp_secret` to users).
6. Email delivery is console-only (provider interface exists).
7. SQLite file readable by host users; no encryption at rest.
8. No security headers middleware yet (HSTS/CSP/X-Frame-Options).

## Testing

`tests/test_auth.py` covers enumeration, token expiry, revocation, tenant
escape, and role rejection. IDOR/XSS/upload abuse tests arrive with those
features (no uploads exist yet).

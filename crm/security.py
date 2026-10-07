"""
Security primitives: password hashing, session + single-use tokens.
Sessions are DB rows (listable/revocable). Cookies are httponly.
"""

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

SESSION_TTL_DAYS = 30
IDLE_TIMEOUT_SECONDS = int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS", "3600"))
RESET_TTL_HOURS = 2
VERIFY_TTL_DAYS = 7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("pbkdf2:"):
        return False
    try:
        _, salt_hex, digest_hex = stored.split(":")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                     bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def check_strength(password: str) -> str | None:
    """Return an error message, or None when acceptable."""
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if not any(c.islower() for c in password) or not any(c.isupper() for c in password):
        return "Password needs upper- and lower-case letters."
    if not any(c.isdigit() for c in password):
        return "Password needs at least one digit."
    return None


def mint_token() -> tuple[str, str]:
    """Return (public_token, sha256_hex) — store only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def create_session(user_id: str, org_id: str | None = None,
                   user_agent: str = "", ip: str = "") -> str:
    from crm import db

    raw, digest = mint_token()
    db.execute(
        "INSERT INTO sessions (id, user_id, org_id, token_hash, user_agent, ip,"
        " created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), user_id, org_id, digest, user_agent[:300], ip[:100], _now(), _now()))
    return raw


def read_session(raw: str | None) -> dict | None:
    """Validate cookie token -> session+user dict, or None. Touches last_seen."""
    if not raw:
        return None
    from crm import db

    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = db.fetchone(
        "SELECT s.id, s.user_id, s.org_id, s.last_seen, s.revoked_at, u.email, u.name "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (digest,))
    if not row or row["revoked_at"]:
        return None
    try:
        idle = (datetime.now(timezone.utc)
                - datetime.fromisoformat(row["last_seen"])).total_seconds()
    except ValueError:
        idle = 0
    if idle > IDLE_TIMEOUT_SECONDS:
        return None
    db.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (_now(), row["id"]))
    return {"session_id": row["id"], "user_id": row["user_id"], "org_id": row["org_id"],
            "email": row["email"], "name": row["name"]}


def revoke_session(session_id: str, user_id: str) -> bool:
    from crm import db

    with db._lock, db._connect() as conn:
        cur = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            (_now(), session_id, user_id))
        return cur.rowcount > 0


def revoke_all_sessions(user_id: str) -> int:
    from crm import db

    with db._lock, db._connect() as conn:
        cur = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (_now(), user_id))
        return cur.rowcount


def cleanup_expired() -> dict:
    """Revoke stale sessions / purge used tokens. Returns counts."""
    from crm import db

    cutoff = (datetime.now(timezone.utc) - timedelta(days=SESSION_TTL_DAYS)).isoformat()
    with db._lock, db._connect() as conn:
        s = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE revoked_at IS NULL AND created_at < ?",
            (_now(), cutoff)).rowcount
        conn.execute("DELETE FROM password_resets WHERE used_at IS NOT NULL OR expires_at < ?",
                     (_now(),))
        conn.execute("DELETE FROM invites WHERE accepted_at IS NOT NULL")
    return {"sessions_revoked": s}

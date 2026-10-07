"""
Auth service: register (with org), login, sessions, password change/reset,
email verification, invites. All rules enforced here, not in routes.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from crm import db, rbac
from crm.security import check_strength, hash_password, mint_token, new_id, verify_password
from crm.services import activity as act
from crm.services import emailing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthError(Exception):
    pass


def register(name: str, email: str, password: str, org_name: str,
             ip: str = "", user_agent: str = "") -> dict:
    email = email.strip().lower()
    if db.fetchone("SELECT id FROM users WHERE email = ?", (email,)):
        raise AuthError("An account with this email already exists.")
    if msg := check_strength(password):
        raise AuthError(msg)
    user_id, org_id = new_id(), new_id()
    now = _now()
    db.execute("INSERT INTO users (id, email, name, password_hash, created_at)"
               " VALUES (?, ?, ?, ?, ?)", (user_id, email, name.strip(), hash_password(password), now))
    db.execute("INSERT INTO organizations (id, name, created_at) VALUES (?, ?, ?)",
               (org_id, org_name.strip(), now))
    db.execute("INSERT INTO organization_members (id, org_id, user_id, role, created_at)"
               " VALUES (?, ?, ?, 'owner', ?)", (new_id(), org_id, user_id, now))
    _send_verification(user_id)
    act.audit(org_id, "user.registered", "user", user_id, actor_id=user_id,
              after={"email": email}, ip=ip, user_agent=user_agent)
    return {"user_id": user_id, "org_id": org_id}


def login(email: str, password: str) -> dict | None:
    user = db.fetchone("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user


def default_org(user_id: str) -> dict | None:
    return db.fetchone(
        "SELECT o.* FROM organizations o JOIN organization_members m ON m.org_id = o.id "
        "WHERE m.user_id = ? ORDER BY m.created_at LIMIT 1", (user_id,))


def switch_org(user_id: str, org_id: str) -> bool:
    return db.fetchone(
        "SELECT id FROM organization_members WHERE org_id = ? AND user_id = ?",
        (org_id, user_id)) is not None


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    user = db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user or not verify_password(current_password, user["password_hash"]):
        raise AuthError("Current password is incorrect.")
    if msg := check_strength(new_password):
        raise AuthError(msg)
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (hash_password(new_password), user_id))


def request_password_reset(email: str) -> str | None:
    """Create reset token; returns raw token (emailed; also returned for tests)."""
    user = db.fetchone("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    if not user:
        return None  # same response either way — no account enumeration
    raw, digest = mint_token()
    exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    db.execute("INSERT INTO password_resets (id, user_id, token_hash, expires_at, created_at)"
               " VALUES (?, ?, ?, ?, ?)", (new_id(), user["id"], digest, exp, _now()))
    emailing.get_provider().send(
        user["email"], "Reset your password",
        f"Use this token within 2 hours:\n\n{raw}\n")
    return raw


def reset_password(token: str, new_password: str) -> None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = db.fetchone(
        "SELECT * FROM password_resets WHERE token_hash = ? AND used_at IS NULL", (digest,))
    if not row or row["expires_at"] < _now():
        raise AuthError("Reset token is invalid or expired.")
    if msg := check_strength(new_password):
        raise AuthError(msg)
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (hash_password(new_password), row["user_id"]))
    db.execute("UPDATE password_resets SET used_at = ? WHERE id = ?", (_now(), row["id"]))
    from crm.security import revoke_all_sessions

    revoke_all_sessions(row["user_id"])


def _send_verification(user_id: str) -> str:
    raw, digest = mint_token()
    exp = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    db.execute("INSERT OR REPLACE INTO email_verifications (user_id, token_hash, expires_at, created_at)"
               " VALUES (?, ?, ?, ?)", (user_id, digest, exp, _now()))
    user = db.fetchone("SELECT email FROM users WHERE id = ?", (user_id,))
    emailing.get_provider().send(
        user["email"], "Verify your email",
        f"Use this token within 7 days:\n\n{raw}\n")
    return raw


def resend_verification(user_id: str) -> None:
    user = db.fetchone("SELECT verified_at FROM users WHERE id = ?", (user_id,))
    if user and not user["verified_at"]:
        _send_verification(user_id)


def verify_email(token: str) -> bool:
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = db.fetchone("SELECT * FROM email_verifications WHERE token_hash = ?", (digest,))
    if not row or row["expires_at"] < _now():
        return False
    db.execute("UPDATE users SET verified_at = ? WHERE id = ?", (_now(), row["user_id"]))
    db.execute("DELETE FROM email_verifications WHERE user_id = ?", (row["user_id"],))
    return True


def invite(org_id: str, email: str, role: str, actor_id: str) -> str:
    email = email.strip().lower()
    if db.fetchone("SELECT id FROM users WHERE email = ?", (email,)):
        member = db.fetchone(
            "SELECT id FROM organization_members WHERE org_id = ? AND user_id = "
            "(SELECT id FROM users WHERE email = ?)", (org_id, email))
        if member:
            raise AuthError("User is already a member.")
    raw, digest = mint_token()
    exp = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    db.execute("INSERT INTO invites (id, org_id, email, role, token_hash, expires_at, created_at)"
               " VALUES (?, ?, ?, ?, ?, ?, ?)",
               (new_id(), org_id, email, role, digest, exp, _now()))
    emailing.get_provider().send(email, "You are invited", f"Invite token:\n\n{raw}\n")
    return raw


def accept_invite(token: str, name: str, password: str) -> dict:
    digest = hashlib.sha256(token.encode()).hexdigest()
    inv = db.fetchone(
        "SELECT * FROM invites WHERE token_hash = ? AND accepted_at IS NULL", (digest,))
    if not inv or inv["expires_at"] < _now():
        raise AuthError("Invite is invalid or expired.")
    if msg := check_strength(password):
        raise AuthError(msg)
    user = db.fetchone("SELECT * FROM users WHERE email = ?", (inv["email"],))
    if user is None:
        user_id = new_id()
        db.execute("INSERT INTO users (id, email, name, password_hash, verified_at, created_at)"
                   " VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, inv["email"], name.strip(), hash_password(password), _now(), _now()))
    else:
        user_id = user["id"]
    if not db.fetchone("SELECT id FROM organization_members WHERE org_id = ? AND user_id = ?",
                       (inv["org_id"], user_id)):
        db.execute("INSERT INTO organization_members (id, org_id, user_id, role, created_at)"
                   " VALUES (?, ?, ?, ?, ?)", (new_id(), inv["org_id"], user_id, inv["role"], _now()))
    db.execute("UPDATE invites SET accepted_at = ? WHERE id = ?", (_now(), inv["id"]))
    act.audit(inv["org_id"], "member.joined", "user", user_id, actor_id=user_id)
    return {"user_id": user_id, "org_id": inv["org_id"]}

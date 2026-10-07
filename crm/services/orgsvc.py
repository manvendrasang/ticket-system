"""
Organization service: settings, members, teams, invites listing.
"""

from crm import db, rbac
from crm.security import new_id


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def get_org(org_id: str) -> dict | None:
    return db.fetchone("SELECT * FROM organizations WHERE id = ?", (org_id,))


def update_org(org_id: str, actor_id: str, ip: str, ua: str, **fields) -> dict:
    before = get_org(org_id)
    allowed = {k: v for k, v in fields.items()
               if k in ("name", "currency", "timezone", "locale") and v is not None}
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        db.execute(f"UPDATE organizations SET {sets} WHERE id = ?",
                   (*allowed.values(), org_id))
    after = get_org(org_id)
    from crm.services import activity as act

    act.audit(org_id, "organization.updated", "organization", org_id,
              actor_id=actor_id, before=before, after=after, ip=ip, user_agent=ua)
    return after


def members(org_id: str) -> list[dict]:
    return db.fetchall(
        "SELECT m.id, m.role, u.id AS user_id, u.email, u.name, m.created_at "
        "FROM organization_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? ORDER BY m.created_at", (org_id,))


def change_role(org_id: str, actor_id: str, target_user_id: str, role: str,
                ip: str, ua: str) -> None:
    if role not in rbac.ROLES:
        raise ValueError(f"unknown role: {role}")
    # Never orphan the org: at least one owner must remain.
    if role != rbac.OWNER:
        owners = db.fetchone(
            "SELECT COUNT(*) AS n FROM organization_members WHERE org_id = ? AND role = 'owner'",
            (org_id,))["n"]
        current = db.fetchone(
            "SELECT role FROM organization_members WHERE org_id = ? AND user_id = ?",
            (org_id, target_user_id))
        if current and current["role"] == rbac.OWNER and owners <= 1:
            raise ValueError("Cannot demote the last owner.")
    db.execute("UPDATE organization_members SET role = ? WHERE org_id = ? AND user_id = ?",
               (role, org_id, target_user_id))
    from crm.services import activity as act

    act.audit(org_id, "member.role_changed", "user", target_user_id,
              actor_id=actor_id, after={"role": role}, ip=ip, user_agent=ua)


def remove_member(org_id: str, actor_id: str, target_user_id: str, ip: str, ua: str) -> None:
    current = db.fetchone(
        "SELECT role FROM organization_members WHERE org_id = ? AND user_id = ?",
        (org_id, target_user_id))
    if current and current["role"] == rbac.OWNER:
        owners = db.fetchone(
            "SELECT COUNT(*) AS n FROM organization_members WHERE org_id = ? AND role = 'owner'",
            (org_id,))["n"]
        if owners <= 1:
            raise ValueError("Cannot remove the last owner.")
    db.execute("DELETE FROM organization_members WHERE org_id = ? AND user_id = ?",
               (org_id, target_user_id))
    from crm.services import activity as act

    act.audit(org_id, "member.removed", "user", target_user_id,
              actor_id=actor_id, ip=ip, user_agent=ua)


def teams(org_id: str) -> list[dict]:
    rows = db.fetchall("SELECT * FROM teams WHERE org_id = ? ORDER BY name", (org_id,))
    for t in rows:
        t["members"] = db.fetchall(
            "SELECT u.id, u.email, u.name FROM team_members tm "
            "JOIN users u ON u.id = tm.user_id WHERE tm.team_id = ?", (t["id"],))
    return rows


def create_team(org_id: str, name: str, actor_id: str, ip: str, ua: str) -> dict:
    tid = new_id()
    db.execute("INSERT INTO teams (id, org_id, name, created_at) VALUES (?, ?, ?, ?)",
               (tid, org_id, name.strip(), _now()))
    from crm.services import activity as act

    act.audit(org_id, "team.created", "team", tid, actor_id=actor_id, ip=ip, user_agent=ua)
    return db.fetchone("SELECT * FROM teams WHERE id = ?", (tid,))

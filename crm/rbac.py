"""
RBAC: fixed roles, permission matrix, server-side checks.
Custom roles later = new entries in ROLE_PERMISSIONS (DB-backed in phase 2).
"""

OWNER = "owner"
ADMIN = "admin"
MANAGER = "manager"
SALES = "sales"
VIEWER = "viewer"

ROLES = (OWNER, ADMIN, MANAGER, SALES, VIEWER)


def _crud(resource: str, extra: tuple[str, ...] = ()) -> set[str]:
    return {f"{resource}.{v}" for v in ("read", "create", "update", "delete")} | set(extra)


ORG = {"organization.read", "organization.update"}
USERS = {"users.read", "users.invite", "users.update", "users.remove"}
REPORTS = {"reports.read", "reports.create"}
SETTINGS = {"settings.read", "settings.update"}
AUDIT = {"audit.read"}

ROLE_PERMISSIONS: dict[str, frozenset] = {
    OWNER: frozenset(
        ORG | USERS | REPORTS | SETTINGS | AUDIT
        | _crud("contacts", {"contacts.assign", "contacts.archive"})
        | _crud("companies", {"companies.assign", "companies.archive"})
        | _crud("leads") | _crud("deals") | _crud("pipelines")
        | _crud("activities") | _crud("tasks") | _crud("notes")),
    ADMIN: frozenset(
        ORG | USERS | REPORTS | SETTINGS | AUDIT
        | _crud("contacts", {"contacts.assign", "contacts.archive"})
        | _crud("companies", {"companies.assign", "companies.archive"})
        | _crud("leads") | _crud("deals") | _crud("pipelines")
        | _crud("activities") | _crud("tasks") | _crud("notes")),
    MANAGER: frozenset(
        REPORTS | {"users.read"}
        | _crud("contacts", {"contacts.assign"})
        | _crud("companies", {"companies.assign"})
        | _crud("leads") | _crud("deals")
        | {"pipelines.read"} | _crud("activities") | _crud("tasks") | _crud("notes")),
    SALES: frozenset(
        {"contacts.read", "contacts.create", "contacts.update",
         "companies.read", "companies.create", "companies.update",
         "leads.read", "leads.create", "leads.update",
         "deals.read", "deals.create", "deals.update",
         "pipelines.read", "activities.read", "activities.create",
         "tasks.read", "tasks.create", "tasks.update",
         "notes.read", "notes.create", "notes.update"}),
    VIEWER: frozenset(
        {"contacts.read", "companies.read", "leads.read", "deals.read",
         "pipelines.read", "activities.read", "tasks.read", "notes.read",
         "reports.read"}),
}


class PermissionDenied(Exception):
    pass


def can(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require(role: str, permission: str) -> None:
    if not can(role, permission):
        raise PermissionDenied(f"role '{role}' lacks '{permission}'")


def member_role(org_id: str, user_id: str) -> str | None:
    from crm import db

    row = db.fetchone(
        "SELECT role FROM organization_members WHERE org_id = ? AND user_id = ?",
        (org_id, user_id))
    return row["role"] if row else None

"""
CRM records: contacts, companies, notes, tasks, tags, activities,
global search, dashboard KPIs. Tenant isolation enforced in every query.
"""

from crm import db
from crm.security import new_id


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


CONTACT_STATUSES = {"active", "inactive", "archived"}
CONTACT_STAGES = {"lead", "prospect", "customer", "churned"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}
TASK_STATUSES = {"todo", "in_progress", "completed", "cancelled"}
ACTIVITY_TYPES = {"call", "email", "meeting", "task", "note", "status_change",
                  "created", "assignment", "comment", "upload"}


def _clean_tags(org_id: str, names: list[str]) -> list[str]:
    ids = []
    for raw in names or []:
        name = (raw or "").strip()[:60]
        if not name:
            continue
        row = db.fetchone("SELECT id FROM tags WHERE org_id = ? AND name = ?", (org_id, name))
        if not row:
            tid = new_id()
            db.execute("INSERT INTO tags (id, org_id, name, created_at) VALUES (?, ?, ?, ?)",
                       (tid, org_id, name, _now()))
            ids.append(tid)
        else:
            ids.append(row["id"])
    return ids


# ─── contacts ─────────────────────────────────────────────────────────────

def _contact_row(org_id: str, contact_id: str) -> dict | None:
    return db.fetchone("SELECT * FROM contacts WHERE id = ? AND org_id = ?", (contact_id, org_id))


def create_contact(org_id: str, actor_id: str, data: dict, ip: str, ua: str) -> dict:
    from crm.services import activity as act

    if data.get("status", "active") not in CONTACT_STATUSES:
        raise ValueError("invalid status")
    if data.get("lifecycle_stage", "lead") not in CONTACT_STAGES:
        raise ValueError("invalid lifecycle_stage")
    if data.get("email"):
        dup = db.fetchone(
            "SELECT id FROM contacts WHERE org_id = ? AND email = ? AND deleted_at IS NULL",
            (org_id, data["email"].strip().lower()))
        if dup:
            raise ValueError(f"Duplicate contact email (id {dup['id']}). Merge instead of duplicating.")
    cid = new_id()
    now = _now()
    db.execute(
        """INSERT INTO contacts (id, org_id, first_name, last_name, email, secondary_email,
           phone, mobile_phone, job_title, department, company_id, owner_id, source, status,
           lifecycle_stage, address, city, state, postal_code, country, website, linkedin_url,
           birthday, description, created_at, updated_at, created_by, updated_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, org_id, data.get("first_name", ""), data.get("last_name", ""),
         (data.get("email") or None), data.get("secondary_email"), data.get("phone"),
         data.get("mobile_phone"), data.get("job_title"), data.get("department"),
         data.get("company_id"), data.get("owner_id"), data.get("source"),
         data.get("status", "active"), data.get("lifecycle_stage", "lead"),
         data.get("address"), data.get("city"), data.get("state"), data.get("postal_code"),
         data.get("country"), data.get("website"), data.get("linkedin_url"),
         data.get("birthday"), data.get("description"), now, now, actor_id, actor_id))
    for tid in _clean_tags(org_id, data.get("tags", [])):
        db.execute("INSERT OR IGNORE INTO contact_tags VALUES (?, ?)", (cid, tid))
    after = _contact_row(org_id, cid)
    act.audit(org_id, "contact.created", "contact", cid, actor_id=actor_id,
              after=after, ip=ip, user_agent=ua)
    act.activity(org_id, "created", f"Contact {after['first_name']} {after['last_name']} created",
                 actor_id=actor_id, entity_type="contact", entity_id=cid)
    return after


def list_contacts(org_id: str, filters: dict, page: int = 1, page_size: int = 25,
                  sort: str = "updated_at", direction: str = "desc") -> tuple[list[dict], int]:
    allowed_sort = {"first_name", "created_at", "updated_at", "owner_id", "status"}
    sort = sort if sort in allowed_sort else "updated_at"
    direction = "ASC" if direction == "asc" else "DESC"
    where, params = ["org_id = ? AND deleted_at IS NULL"], [org_id]
    for key in ("status", "lifecycle_stage", "owner_id", "company_id"):
        if filters.get(key):
            where.append(f"{key} = ?")
            params.append(filters[key])
    if filters.get("q"):
        where.append("(first_name LIKE ? OR last_name LIKE ? OR email LIKE ?)")
        q = f"%{filters['q']}%"
        params += [q, q, q]
    if filters.get("tag"):
        where.append("id IN (SELECT contact_id FROM contact_tags ct JOIN tags t ON t.id = ct.tag_id"
                     " WHERE t.org_id = ? AND t.name = ?)")
        params += [org_id, filters["tag"]]
    total = db.fetchone(f"SELECT COUNT(*) AS n FROM contacts WHERE {' AND '.join(where)}",
                        tuple(params))["n"]
    rows = db.fetchall(
        f"SELECT * FROM contacts WHERE {' AND '.join(where)} ORDER BY {sort} {direction}"
        " LIMIT ? OFFSET ?", tuple(params + [page_size, (page - 1) * page_size]))
    return rows, total


def update_contact(org_id: str, contact_id: str, actor_id: str, data: dict,
                   ip: str, ua: str) -> dict | None:
    from crm.services import activity as act

    before = _contact_row(org_id, contact_id)
    if not before or before["deleted_at"]:
        return None
    allowed = ("first_name", "last_name", "email", "secondary_email", "phone", "mobile_phone",
               "job_title", "department", "company_id", "owner_id", "source", "status",
               "lifecycle_stage", "address", "city", "state", "postal_code", "country",
               "website", "linkedin_url", "birthday", "description")
    patch = {k: data[k] for k in allowed if k in data}
    if "email" in patch and patch["email"]:
        dup = db.fetchone(
            "SELECT id FROM contacts WHERE org_id = ? AND email = ? AND id != ? AND deleted_at IS NULL",
            (org_id, patch["email"].strip().lower(), contact_id))
        if dup:
            raise ValueError(f"Duplicate contact email (id {dup['id']}).")
    if patch:
        patch["updated_at"] = _now()
        patch["updated_by"] = actor_id
        db.execute(f"UPDATE contacts SET {', '.join(f'{k} = ?' for k in patch)} WHERE id = ?",
                   (*patch.values(), contact_id))
    if "tags" in data:
        db.execute("DELETE FROM contact_tags WHERE contact_id = ?", (contact_id,))
        for tid in _clean_tags(org_id, data["tags"]):
            db.execute("INSERT OR IGNORE INTO contact_tags VALUES (?, ?)", (contact_id, tid))
    after = _contact_row(org_id, contact_id)
    act.audit(org_id, "contact.updated", "contact", contact_id, actor_id=actor_id,
              before=before, after=after, ip=ip, user_agent=ua)
    return after


def archive_contact(org_id: str, contact_id: str, actor_id: str, ip: str, ua: str,
                    archived: bool = True) -> bool:
    before = _contact_row(org_id, contact_id)
    if not before:
        return False
    db.execute("UPDATE contacts SET archived = ?, updated_at = ? WHERE id = ?",
               (1 if archived else 0, _now(), contact_id))
    from crm.services import activity as act

    act.audit(org_id, "contact.archived" if archived else "contact.restored",
              "contact", contact_id, actor_id=actor_id, before=before, ip=ip, user_agent=ua)
    return True


def delete_contact(org_id: str, contact_id: str, actor_id: str, ip: str, ua: str) -> bool:
    before = _contact_row(org_id, contact_id)
    if not before:
        return False
    db.execute("UPDATE contacts SET deleted_at = ?, deleted_by = ? WHERE id = ?",
               (_now(), actor_id, contact_id))
    from crm.services import activity as act

    act.audit(org_id, "contact.deleted", "contact", contact_id, actor_id=actor_id,
              before=before, ip=ip, user_agent=ua)
    return True


def contact_detail(org_id: str, contact_id: str) -> dict | None:
    c = _contact_row(org_id, contact_id)
    if not c or c["deleted_at"]:
        return None
    c["tags"] = [r["name"] for r in db.fetchall(
        "SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id = t.id WHERE ct.contact_id = ?",
        (contact_id,))]
    c["notes"] = db.fetchall(
        "SELECT * FROM notes WHERE org_id = ? AND entity_type = 'contact' AND entity_id = ?"
        " ORDER BY created_at DESC", (org_id, contact_id))
    c["tasks"] = db.fetchall(
        "SELECT * FROM tasks WHERE org_id = ? AND related_type = 'contact' AND related_id = ?"
        " ORDER BY due_date", (org_id, contact_id))
    c["timeline"] = db.fetchall(
        "SELECT * FROM activities WHERE org_id = ? AND entity_type = 'contact' AND entity_id = ?"
        " ORDER BY created_at DESC LIMIT 100", (org_id, contact_id))
    return c


# ─── companies ────────────────────────────────────────────────────────────

def _company_row(org_id: str, company_id: str) -> dict | None:
    return db.fetchone("SELECT * FROM companies WHERE id = ? AND org_id = ?", (company_id, org_id))


def create_company(org_id: str, actor_id: str, data: dict, ip: str, ua: str) -> dict:
    from crm.services import activity as act

    dup = db.fetchone(
        "SELECT id FROM companies WHERE org_id = ? AND LOWER(name) = LOWER(?) AND deleted_at IS NULL",
        (org_id, data["name"].strip()))
    if dup:
        raise ValueError(f"Duplicate company name (id {dup['id']}).")
    cid, now = new_id(), _now()
    db.execute(
        """INSERT INTO companies (id, org_id, name, industry, website, email, phone,
           employee_count, annual_revenue, owner_id, status, description, address, city,
           state, postal_code, country, created_at, updated_at, created_by, updated_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, org_id, data["name"].strip(), data.get("industry"), data.get("website"),
         data.get("email"), data.get("phone"), data.get("employee_count"),
         data.get("annual_revenue"), data.get("owner_id"), data.get("status", "active"),
         data.get("description"), data.get("address"), data.get("city"), data.get("state"),
         data.get("postal_code"), data.get("country"), now, now, actor_id, actor_id))
    for tid in _clean_tags(org_id, data.get("tags", [])):
        db.execute("INSERT OR IGNORE INTO company_tags VALUES (?, ?)", (cid, tid))
    after = _company_row(org_id, cid)
    act.audit(org_id, "company.created", "company", cid, actor_id=actor_id,
              after=after, ip=ip, user_agent=ua)
    act.activity(org_id, "created", f"Company {after['name']} created",
                 actor_id=actor_id, entity_type="company", entity_id=cid)
    return after


def list_companies(org_id: str, filters: dict, page: int = 1, page_size: int = 25) -> tuple[list[dict], int]:
    where, params = ["org_id = ? AND deleted_at IS NULL"], [org_id]
    for key in ("status", "industry", "owner_id"):
        if filters.get(key):
            where.append(f"{key} = ?")
            params.append(filters[key])
    if filters.get("q"):
        where.append("(name LIKE ? OR email LIKE ? OR website LIKE ?)")
        q = f"%{filters['q']}%"
        params += [q, q, q]
    total = db.fetchone(f"SELECT COUNT(*) AS n FROM companies WHERE {' AND '.join(where)}",
                        tuple(params))["n"]
    rows = db.fetchall(
        f"SELECT * FROM companies WHERE {' AND '.join(where)} ORDER BY updated_at DESC"
        " LIMIT ? OFFSET ?", tuple(params + [page_size, (page - 1) * page_size]))
    return rows, total


def update_company(org_id: str, company_id: str, actor_id: str, data: dict,
                   ip: str, ua: str) -> dict | None:
    from crm.services import activity as act

    before = _company_row(org_id, company_id)
    if not before or before["deleted_at"]:
        return None
    allowed = ("name", "industry", "website", "email", "phone", "employee_count",
               "annual_revenue", "owner_id", "status", "description", "address",
               "city", "state", "postal_code", "country")
    patch = {k: data[k] for k in allowed if k in data}
    if "name" in patch:
        dup = db.fetchone(
            "SELECT id FROM companies WHERE org_id = ? AND LOWER(name) = LOWER(?)"
            " AND id != ? AND deleted_at IS NULL", (org_id, patch["name"].strip(), company_id))
        if dup:
            raise ValueError(f"Duplicate company name (id {dup['id']}).")
    if patch:
        patch["updated_at"] = _now()
        patch["updated_by"] = actor_id
        db.execute(f"UPDATE companies SET {', '.join(f'{k} = ?' for k in patch)} WHERE id = ?",
                   (*patch.values(), company_id))
    if "tags" in data:
        db.execute("DELETE FROM company_tags WHERE company_id = ?", (company_id,))
        for tid in _clean_tags(org_id, data["tags"]):
            db.execute("INSERT OR IGNORE INTO company_tags VALUES (?, ?)", (company_id, tid))
    after = _company_row(org_id, company_id)
    act.audit(org_id, "company.updated", "company", company_id, actor_id=actor_id,
              before=before, after=after, ip=ip, user_agent=ua)
    return after


def delete_company(org_id: str, company_id: str, actor_id: str, ip: str, ua: str) -> bool:
    before = _company_row(org_id, company_id)
    if not before:
        return False
    linked = db.fetchone(
        "SELECT COUNT(*) AS n FROM contacts WHERE company_id = ? AND deleted_at IS NULL",
        (company_id,))["n"]
    if linked:
        raise ValueError(f"Company has {linked} active contact(s); reassign them first.")
    db.execute("UPDATE companies SET deleted_at = ?, deleted_by = ? WHERE id = ?",
               (_now(), actor_id, company_id))
    from crm.services import activity as act

    act.audit(org_id, "company.deleted", "company", company_id, actor_id=actor_id,
              before=before, ip=ip, user_agent=ua)
    return True


def company_detail(org_id: str, company_id: str) -> dict | None:
    c = _company_row(org_id, company_id)
    if not c or c["deleted_at"]:
        return None
    c["tags"] = [r["name"] for r in db.fetchall(
        "SELECT t.name FROM tags t JOIN company_tags ct ON ct.tag_id = t.id WHERE ct.company_id = ?",
        (company_id,))]
    c["contacts"] = db.fetchall(
        "SELECT id, first_name, last_name, email FROM contacts "
        "WHERE company_id = ? AND deleted_at IS NULL", (company_id,))
    c["notes"] = db.fetchall(
        "SELECT * FROM notes WHERE org_id = ? AND entity_type = 'company' AND entity_id = ?"
        " ORDER BY created_at DESC", (org_id, company_id))
    c["tasks"] = db.fetchall(
        "SELECT * FROM tasks WHERE org_id = ? AND related_type = 'company' AND related_id = ?"
        " ORDER BY due_date", (org_id, company_id))
    c["timeline"] = db.fetchall(
        "SELECT * FROM activities WHERE org_id = ? AND entity_type = 'company' AND entity_id = ?"
        " ORDER BY created_at DESC LIMIT 100", (org_id, company_id))
    return c


# ─── notes / tasks / tags ─────────────────────────────────────────────────

def add_note(org_id: str, author_id: str, entity_type: str, entity_id: str,
             body: str, ip: str, ua: str) -> dict:
    from crm.services import activity as act

    if entity_type not in ("contact", "company"):
        raise ValueError("notes attach to contact or company in phase 1")
    nid = new_id()
    now = _now()
    db.execute("INSERT INTO notes (id, org_id, author_id, entity_type, entity_id, body,"
               " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (nid, org_id, author_id, entity_type, entity_id, body, now, now))
    act.audit(org_id, "note.created", "note", nid, actor_id=author_id, ip=ip, user_agent=ua)
    act.activity(org_id, "note", body[:140], actor_id=author_id,
                 entity_type=entity_type, entity_id=entity_id)
    return db.fetchone("SELECT * FROM notes WHERE id = ?", (nid,))


def create_task(org_id: str, creator_id: str, data: dict, ip: str, ua: str) -> dict:
    from crm.services import activity as act

    if data.get("priority", "medium") not in TASK_PRIORITIES:
        raise ValueError("invalid priority")
    if data.get("status", "todo") not in TASK_STATUSES:
        raise ValueError("invalid status")
    tid, now = new_id(), _now()
    db.execute(
        "INSERT INTO tasks (id, org_id, title, description, assignee_id, creator_id, due_date,"
        " priority, status, related_type, related_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tid, org_id, data["title"].strip(), data.get("description", ""),
         data.get("assignee_id"), creator_id, data.get("due_date"),
         data.get("priority", "medium"), data.get("status", "todo"),
         data.get("related_type"), data.get("related_id"), now, now))
    if data.get("assignee_id") and data["assignee_id"] != creator_id:
        act.notify(org_id, data["assignee_id"], "task_assigned",
                   f"Task assigned: {data['title']}", link=f"/tasks/{tid}")
    act.audit(org_id, "task.created", "task", tid, actor_id=creator_id, ip=ip, user_agent=ua)
    return db.fetchone("SELECT * FROM tasks WHERE id = ?", (tid,))


def complete_task(org_id: str, task_id: str, actor_id: str, ip: str, ua: str,
                  status: str = "completed") -> dict | None:
    from crm.services import activity as act

    if status not in TASK_STATUSES:
        raise ValueError("invalid status")
    task = db.fetchone("SELECT * FROM tasks WHERE id = ? AND org_id = ?", (task_id, org_id))
    if not task:
        return None
    db.execute("UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
               (status, _now() if status == "completed" else None, _now(), task_id))
    act.audit(org_id, "task.status_changed", "task", task_id, actor_id=actor_id,
              before={"status": task["status"]}, after={"status": status}, ip=ip, user_agent=ua)
    return db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))


def list_tasks(org_id: str, filters: dict, page: int = 1, page_size: int = 25) -> tuple[list[dict], int]:
    where, params = ["org_id = ?"], [org_id]
    for key in ("status", "priority", "assignee_id"):
        if filters.get(key):
            where.append(f"{key} = ?")
            params.append(filters[key])
    if filters.get("overdue") == "true":
        where.append("status NOT IN ('completed','cancelled') AND due_date IS NOT NULL"
                     " AND due_date < date('now')")
    total = db.fetchone(f"SELECT COUNT(*) AS n FROM tasks WHERE {' AND '.join(where)}",
                        tuple(params))["n"]
    rows = db.fetchall(
        f"SELECT * FROM tasks WHERE {' AND '.join(where)} ORDER BY due_date LIMIT ? OFFSET ?",
        tuple(params + [page_size, (page - 1) * page_size]))
    return rows, total


# ─── search + dashboard ───────────────────────────────────────────────────

def global_search(org_id: str, query: str, limit: int = 8) -> dict:
    q = f"%{query.strip()}%"
    contacts = db.fetchall(
        "SELECT id, first_name, last_name, email FROM contacts WHERE org_id = ?"
        " AND deleted_at IS NULL AND (first_name LIKE ? OR last_name LIKE ? OR email LIKE ?)"
        " LIMIT ?", (org_id, q, q, q, limit))
    companies = db.fetchall(
        "SELECT id, name FROM companies WHERE org_id = ? AND deleted_at IS NULL"
        " AND (name LIKE ? OR email LIKE ?) LIMIT ?", (org_id, q, q, limit))
    tasks = db.fetchall(
        "SELECT id, title FROM tasks WHERE org_id = ? AND title LIKE ? LIMIT ?", (org_id, q, limit))
    return {"contacts": contacts, "companies": companies, "tasks": tasks}


def dashboard_kpis(org_id: str) -> dict:
    one = lambda sql, p=(): db.fetchone(sql, (org_id,) + tuple(p))
    return {
        "contacts": one("SELECT COUNT(*) AS n FROM contacts WHERE org_id = ? AND deleted_at IS NULL")["n"],
        "companies": one("SELECT COUNT(*) AS n FROM companies WHERE org_id = ? AND deleted_at IS NULL")["n"],
        "open_tasks": one("SELECT COUNT(*) AS n FROM tasks WHERE org_id = ? AND status NOT IN ('completed','cancelled')")["n"],
        "overdue_tasks": one("SELECT COUNT(*) AS n FROM tasks WHERE org_id = ? AND status NOT IN ('completed','cancelled')"
                             " AND due_date IS NOT NULL AND due_date < date('now')")["n"],
        "unread_notifications": None,  # per-user; filled by route
        "recent_activity": db.fetchall(
            "SELECT * FROM activities WHERE org_id = ? ORDER BY created_at DESC LIMIT 10", (org_id,)),
        "upcoming_tasks": db.fetchall(
            "SELECT * FROM tasks WHERE org_id = ? AND status NOT IN ('completed','cancelled')"
            " ORDER BY due_date LIMIT 5", (org_id,)),
    }

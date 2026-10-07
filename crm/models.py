"""
Shared request/response schemas. Server is authoritative; every write is
validated here AND re-checked in services (never trust the client).
"""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=EMAIL_RE)
    password: str = Field(min_length=10, max_length=200)
    org_name: str = Field(min_length=1, max_length=160)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class ForgotIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE)


class ResetIn(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=10, max_length=200)


class OrgUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    timezone: Optional[str] = Field(default=None, max_length=60)
    locale: Optional[str] = Field(default=None, max_length=12)


class InviteIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE)
    role: str = "sales"

    @field_validator("role")
    @classmethod
    def known_role(cls, v: str) -> str:
        from crm.rbac import ROLES

        if v not in ROLES:
            raise ValueError(f"unknown role: {v}")
        return v


class AcceptInviteIn(BaseModel):
    token: str
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=200)


class ContactIn(BaseModel):
    first_name: str = Field(default="", max_length=120)
    last_name: str = Field(default="", max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None
    job_title: Optional[str] = None
    company_id: Optional[str] = None
    owner_id: Optional[str] = None
    source: Optional[str] = None
    status: str = "active"
    lifecycle_stage: str = "lead"
    description: Optional[str] = None
    tags: list[str] = []


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    owner_id: Optional[str] = None
    status: str = "active"
    description: Optional[str] = None
    tags: list[str] = []


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "medium"
    status: str = "todo"
    related_type: Optional[str] = None
    related_id: Optional[str] = None


class NoteIn(BaseModel):
    entity_type: str
    entity_id: str
    body: str = Field(min_length=1)


class Page(BaseModel):
    data: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class ErrorBody(BaseModel):
    code: str
    message: str
    field_errors: dict[str, str] = {}
    request_id: str = ""

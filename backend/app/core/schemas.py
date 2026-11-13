"""Pydantic schemas for core endpoints (auth, audit, settings, preferences)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Permission, Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    tenant_id: uuid.UUID | None = Field(
        default=None, description="Company to sign in to. Required if the user has several."
    )


class SwitchCompanyRequest(BaseModel):
    tenant_id: uuid.UUID


class CompanyOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    company: CompanyOut
    companies: list[CompanyOut]
    permissions: list[Permission]


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    at: datetime
    actor_id: uuid.UUID | None
    actor_name: str | None
    action: str
    entity_type: str
    entity_id: str | None
    summary: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class JsonValue(BaseModel):
    """A JSON object stored for a key (settings or preferences)."""

    key: str
    value: dict[str, Any]


class JsonValueIn(BaseModel):
    value: dict[str, Any]


class HealthOut(BaseModel):
    status: str
    database: bool
    redis: bool
    storage: bool
    ai_mode: str

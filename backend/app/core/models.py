"""Core tables: identity (global), tenant keys, audit log, outbox, settings, preferences.

Global tables (no tenant_id): ``tenants``, ``users``. ``memberships`` has its own RLS
policy (visible to its tenant, or to its user during login). Everything else is
tenant-scoped and protected by the standard ``tenant_isolation`` policy.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Bumped on logout-everywhere / password change: invalidates refresh tokens.
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")


class Membership(Base, TimestampMixin):
    """A user's role inside one company (tenant)."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class TenantKey(Base, TenantScoped):
    """The tenant's data-encryption key, wrapped by the KEK. One active key per tenant."""

    __tablename__ = "tenant_keys"
    __table_args__ = (
        Index(
            "uq_tenant_keys_one_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(default=1)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base, TenantScoped):
    """Append-only record of who changed what, and when. Written in the same transaction."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_name: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(64))  # e.g. create, update, delete, login
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))


class OutboxEvent(Base, TenantScoped):
    """Domain events written in the business transaction, dispatched by the worker."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_pending",
            "tenant_id",
            "id",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)


class TenantSetting(Base, TenantScoped, TimestampMixin):
    """Owner-customisable settings (JSONB), e.g. order ranking weights."""

    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)


class UserPreference(Base, TenantScoped, TimestampMixin):
    """Per-user UI state (JSONB), e.g. table columns and saved views."""

    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TenantCounter(Base, TenantScoped):
    """Per-company number sequences (ORD-1042, ...)."""

    __tablename__ = "tenant_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(50))
    value: Mapped[int] = mapped_column(BigInteger, default=0)

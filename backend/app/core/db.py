"""Database engine, base model and the tenant-scoped session.

Every request that touches tenant data runs inside ONE transaction that first sets
``app.tenant_id`` (transaction-local). PostgreSQL row-level security policies compare
each row's ``tenant_id`` with that setting, so a query can never see another
company's rows, even if application code forgets a WHERE clause (Layer 1).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScoped:
    """Mixin for every business table. The migration must call ``enable_tenant_rls``."""

    __tenant_scoped__ = True
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        index=True,
        server_default=text("NULLIF(current_setting('app.tenant_id', true), '')::uuid"),
    )


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind the current transaction to one tenant (transaction-local setting)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """One transaction bound to ``tenant_id``. Commits on success, rolls back on error."""
    async with get_sessionmaker()() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session


@asynccontextmanager
async def global_session() -> AsyncIterator[AsyncSession]:
    """Transaction with NO tenant bound: only global tables (users, tenants) are visible."""
    async with get_sessionmaker()() as session, session.begin():
        yield session

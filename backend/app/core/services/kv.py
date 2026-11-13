"""Tenant settings and per-user preferences: small JSON documents keyed by name."""

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import DomainError, NotFound
from app.core.models import TenantSetting, UserPreference

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,99}$")
MAX_VALUE_BYTES = 64 * 1024


def _check(key: str, value: dict[str, Any] | None = None) -> None:
    if not _KEY_RE.match(key):
        raise DomainError("Key must be lower-case letters, digits, '.', '_' or '-'.")
    if value is not None and len(repr(value)) > MAX_VALUE_BYTES:
        raise DomainError("Value is too large (max 64 KB).")


async def get_setting(session: AsyncSession, key: str) -> dict[str, Any]:
    _check(key)
    row = (
        await session.execute(select(TenantSetting.value).where(TenantSetting.key == key))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Setting {key!r} is not set.")
    value: dict[str, Any] = row
    return value


async def put_setting(
    session: AsyncSession, actor_id: uuid.UUID, key: str, value: dict[str, Any]
) -> dict[str, Any]:
    _check(key, value)
    before = (
        await session.execute(select(TenantSetting.value).where(TenantSetting.key == key))
    ).scalar_one_or_none()
    stmt = insert(TenantSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_={"value": value})
    await session.execute(stmt)
    await audit.record(
        session,
        actor_id=actor_id,
        action="update" if before is not None else "create",
        entity_type="setting",
        entity_id=key,
        summary=f"Setting '{key}' changed",
        before=before,
        after=value,
    )
    return value


async def get_preference(
    session: AsyncSession, user_id: uuid.UUID, key: str
) -> dict[str, Any] | None:
    _check(key)
    return (
        await session.execute(
            select(UserPreference.value).where(
                UserPreference.user_id == user_id, UserPreference.key == key
            )
        )
    ).scalar_one_or_none()


async def put_preference(
    session: AsyncSession, user_id: uuid.UUID, key: str, value: dict[str, Any]
) -> dict[str, Any]:
    _check(key, value)
    stmt = insert(UserPreference).values(user_id=user_id, key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "user_id", "key"], set_={"value": value}
    )
    await session.execute(stmt)
    return value

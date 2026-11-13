"""Audit log writer. Call ``record`` inside the same transaction as the change."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import request_id_var
from app.core.models import AuditLog, User
from app.core.redaction import redact_value


async def record(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    summary: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    actor_name = None
    if actor_id is not None:
        actor_name = (
            await session.execute(select(User.full_name).where(User.id == actor_id))
        ).scalar_one_or_none()
    entry = AuditLog(
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary,
        before=redact_value(before) if before is not None else None,
        after=redact_value(after) if after is not None else None,
        request_id=request_id_var.get(),
    )
    session.add(entry)
    await session.flush()
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep only the keys whose value changed, for compact audit entries."""
    keys = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}

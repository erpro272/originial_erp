"""Domain events via the transactional outbox.

``emit`` writes the event in the caller's transaction, so the event exists if and only
if the business change committed. The worker's ``dispatch_outbox`` job delivers events
to registered handlers per tenant (with that tenant bound, so RLS still applies).
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import global_session, tenant_session
from app.core.models import OutboxEvent

log = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, OutboxEvent], Awaitable[None]]
_handlers: dict[str, list[Handler]] = defaultdict(list)
MAX_ATTEMPTS = 10


def subscribe(event_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _handlers[event_type].append(fn)
        return fn

    return deco


async def emit(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> OutboxEvent:
    event = OutboxEvent(type=event_type, payload=payload)
    session.add(event)
    await session.flush()
    return event


async def _tenant_ids() -> list[uuid.UUID]:
    # SECURITY DEFINER function: lists tenant ids only, for system jobs.
    async with global_session() as s:
        return list((await s.execute(text("SELECT * FROM erp_active_tenant_ids()"))).scalars())


async def dispatch_outbox(batch_size: int = 100) -> int:
    """Deliver pending events. Returns the number processed successfully."""
    done = 0
    for tenant_id in await _tenant_ids():
        async with tenant_session(tenant_id) as s:
            events = (
                await s.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.processed_at.is_(None), OutboxEvent.attempts < MAX_ATTEMPTS)
                    .order_by(OutboxEvent.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
            for event in events:
                try:
                    async with s.begin_nested():
                        for handler in _handlers.get(event.type, []):
                            await handler(s, event)
                    event.processed_at = datetime.now(UTC)
                    done += 1
                except Exception as exc:  # handler failure must not block the queue
                    event.attempts += 1
                    event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                    log.warning("outbox event %s (%s) failed", event.id, event.type)
    return done

"""Gap-tolerant, concurrency-safe per-company counters."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def next_value(session: AsyncSession, name: str, start: int = 1000) -> int:
    row = await session.execute(
        text(
            "INSERT INTO tenant_counters (id, name, value) VALUES (gen_random_uuid(), :n, :s) "
            "ON CONFLICT (tenant_id, name) DO UPDATE SET value = tenant_counters.value + 1 "
            "RETURNING value"
        ),
        {"n": name, "s": start + 1},
    )
    return int(row.scalar_one())


async def ensure_at_least(session: AsyncSession, name: str, value: int) -> None:
    """Used by the seed so new numbers continue after imported ones."""
    await session.execute(
        text(
            "INSERT INTO tenant_counters (id, name, value) VALUES (gen_random_uuid(), :n, :v) "
            "ON CONFLICT (tenant_id, name) DO UPDATE "
            "SET value = GREATEST(tenant_counters.value, EXCLUDED.value)"
        ),
        {"n": name, "v": value},
    )

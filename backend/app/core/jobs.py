"""Background jobs. API code calls `enqueue`; the ARQ worker runs them.

With ERP_JOBS_INLINE=true (tests) jobs run in-process instead, so tests don't need a worker.
"""

import importlib
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_pool: ArqRedis | None = None

# name -> "module:function"
REGISTRY = {
    "extract_invoice": "app.invoices.jobs:extract_invoice",
    "ingest_document": "app.ai.rag.ingestion:ingest_document",
}


def resolve(name: str) -> Any:
    mod, fn = REGISTRY[name].split(":")
    return getattr(importlib.import_module(mod), fn)


async def enqueue(name: str, *args: Any) -> None:
    global _pool
    if get_settings().jobs_inline:
        await resolve(name)({}, *args)
        return
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    await _pool.enqueue_job(name, *args)

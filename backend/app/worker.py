"""ARQ worker: background jobs (invoice extraction, plan calculation, outbox delivery)."""

import asyncio
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.ai.rag.embeddings import get_embedder
from app.ai.rag.ingestion import ingest_document, reindex_stale
from app.core.config import get_settings
from app.core.events import dispatch_outbox
from app.core.logging import configure_logging
from app.invoices.jobs import extract_invoice


async def startup(_: dict[str, Any]) -> None:
    configure_logging()
    await asyncio.to_thread(get_embedder)  # first run downloads the embedding model (~70 MB) once
    await reindex_stale()  # documents indexed by another embedder (e.g. the fallback) are re-indexed


async def outbox_job(_: dict[str, Any]) -> int:
    return await dispatch_outbox()


class WorkerSettings:
    functions: list[Any] = [extract_invoice, ingest_document]
    cron_jobs = [
        cron(
            outbox_job,  # type: ignore[arg-type]  # arq types ctx loosely
            second=set(range(0, 60, 5)),
            run_at_startup=True,
        )
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    job_timeout = 600

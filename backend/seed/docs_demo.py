"""Demo company documents for the AI Assistant (dev seed only): the sample costing policy, CNC safety SOP and
inspection procedure (samples/documents/, regenerate with `python -m scripts.make_sample_documents`), stored encrypted
and indexed in place (same steps as the ingestion job). Idempotent: skipped when the company has documents.
The seed role bypasses RLS: tenant_id is set explicitly."""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import get_embedder
from app.ai.rag.ingestion import chunk, extract, kind_of
from app.ai.rag.models import AiDocument, AiDocumentChunk
from app.ai.rag.service import CTYPE
from app.core import keys
from app.core.db import set_tenant
from app.core.storage import get_storage, put_encrypted, tenant_key

log = logging.getLogger(__name__)
FOLDER = Path(__file__).resolve().parents[2] / "samples" / "documents"
ROLES = {"Costing Policy.pdf": ["owner", "accountant", "planner"]}  # the rest: every role


async def seed_documents(s: AsyncSession, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> int:
    await set_tenant(s, tenant_id)
    if (await s.execute(select(AiDocument.id).where(AiDocument.tenant_id == tenant_id).limit(1))).first():
        return 0
    if not FOLDER.is_dir():
        return 0
    try:
        await get_storage().ensure_bucket()
    except Exception as exc:  # no object storage running: skip the documents, keep the rest of the seed
        log.warning("seed: documents skipped (storage unavailable: %s)", type(exc).__name__)
        return 0
    cipher = await keys.get_cipher(s, tenant_id)
    emb = get_embedder()
    n = 0
    for path in sorted(FOLDER.iterdir()):
        data = path.read_bytes()
        kind = kind_of(path.name, data)
        did = uuid.uuid4()
        key = tenant_key(tenant_id, "documents", str(did), f"original.{kind}")
        await put_encrypted(cipher, key, data)
        pages = extract(kind, data)
        chunks = chunk(pages)
        vecs = emb.embed([c.text for c in chunks])
        s.add(AiDocument(id=did, tenant_id=tenant_id, title=path.stem, file_name=path.name, file_key=key,
                         content_type=CTYPE[kind], size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                         roles=ROLES.get(path.name, []), status="ready", pages=sum(1 for _, t in pages if t.strip()),
                         chunks=len(chunks), embedder=emb.name, uploaded_by=owner_id, indexed_at=datetime.now(UTC)))  # fmt: skip
        await s.flush()
        s.add_all(AiDocumentChunk(tenant_id=tenant_id, document_id=did, seq=c.seq, page=c.page, text=c.text, embedding=v,
                                  embedder=emb.name) for c, v in zip(chunks, vecs, strict=True))  # fmt: skip
        n += 1
    await s.flush()
    return n

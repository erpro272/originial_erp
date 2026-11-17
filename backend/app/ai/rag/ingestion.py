"""Document ingestion (ARQ job `ingest_document`): decrypt -> extract text per page -> chunk -> embed -> store.
PDF (text layer, via pypdfium2), DOCX (python-docx: paragraphs and tables), TXT / Markdown. Scanned PDFs without a
text layer are reported, not guessed at."""

import asyncio
import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete

from app.ai.rag.embeddings import get_embedder
from app.ai.rag.models import AiDocument, AiDocumentChunk
from app.core import keys
from app.core.db import tenant_session
from app.core.storage import get_decrypted

log = logging.getLogger(__name__)
CHUNK = 900  # characters (~200 tokens: small enough to cite precisely, cheap for the free-tier LLM)
OVERLAP = 150
TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "txt",
}


class IngestError(Exception):
    pass


def kind_of(name: str, data: bytes) -> str:
    n = name.lower()
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK" and n.endswith(".docx"):
        return "docx"
    if n.endswith((".txt", ".md")):
        try:
            data[:4096].decode("utf-8")
            return "txt"
        except UnicodeDecodeError:
            pass
    raise IngestError("Upload a PDF, Word (.docx), text or Markdown file.")


def extract(kind: str, data: bytes) -> list[tuple[int | None, str]]:
    """[(page, text)] in reading order."""
    if kind == "pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        out: list[tuple[int | None, str]] = []
        for i in range(len(pdf)):
            tp = pdf[i].get_textpage()
            out.append((i + 1, tp.get_text_range() or ""))
        return out
    if kind == "docx":
        import docx

        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            parts += [" | ".join(c.text.strip() for c in row.cells) for row in t.rows]
        return [(None, "\n".join(parts))]
    return [(None, data.decode("utf-8", errors="replace"))]


@dataclass
class Chunk:
    seq: int
    page: int | None
    text: str


def _clean(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def chunk(pages: list[tuple[int | None, str]]) -> list[Chunk]:
    """Paragraph-aware chunks of about CHUNK characters with OVERLAP, never across pages (so citations are exact)."""
    out: list[Chunk] = []
    for page, raw in pages:
        text = _clean(raw)
        if not text:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z0-9][^\n]{0,80}\n)", text) if p.strip()]
        buf = ""
        for p in paras:
            while len(p) > CHUNK:  # a very long paragraph: split on sentence ends
                cut = max(p.rfind(". ", 0, CHUNK), p.rfind("\n", 0, CHUNK))
                cut = cut + 1 if cut > CHUNK // 2 else CHUNK
                if buf:
                    out.append(Chunk(len(out), page, buf))
                    buf = ""
                out.append(Chunk(len(out), page, p[:cut].strip()))
                p = p[max(cut - OVERLAP, 1) :].strip()
            if len(buf) + len(p) + 2 > CHUNK and buf:
                out.append(Chunk(len(out), page, buf))
                buf = buf[-OVERLAP:].split(" ", 1)[-1] if len(buf) > OVERLAP else ""
            buf = f"{buf}\n\n{p}".strip()
        if buf:
            out.append(Chunk(len(out), page, buf))
    return out


async def ingest_document(_: dict[str, Any], tenant_id: str, document_id: str) -> str:
    tid, did = uuid.UUID(tenant_id), uuid.UUID(document_id)
    async with tenant_session(tid) as s:
        doc = await s.get(AiDocument, did)
        if doc is None or doc.deleted_at is not None:
            return "gone"
        doc.status, doc.error = "processing", None
        cipher = await keys.get_cipher(s, tid)
        key, name = doc.file_key, doc.file_name
    try:
        data = await get_decrypted(cipher, key)
        kind = kind_of(name, data)
        pages = await asyncio.to_thread(extract, kind, data)
        chunks = chunk(pages)
        if not chunks:
            raise IngestError(
                "No text found. Is it a scanned PDF? Upload a PDF with selectable text, or a Word file."
            )
        emb = get_embedder()
        vecs = await asyncio.to_thread(emb.embed, [c.text for c in chunks])
    except IngestError as exc:
        return await _fail(tid, did, str(exc))
    except Exception:
        log.exception("document ingestion failed (%s)", did)
        return await _fail(tid, did, "Couldn't read this file. Try again or upload it in another format.")
    async with tenant_session(tid) as s:
        doc = await s.get(AiDocument, did)
        if doc is None or doc.deleted_at is not None:
            return "gone"
        await s.execute(delete(AiDocumentChunk).where(AiDocumentChunk.document_id == did))
        s.add_all(AiDocumentChunk(document_id=did, seq=c.seq, page=c.page, text=c.text, embedding=v, embedder=emb.name)
                  for c, v in zip(chunks, vecs, strict=True))  # fmt: skip
        doc.status, doc.pages, doc.chunks = "ready", sum(1 for p, t in pages if t.strip()), len(chunks)
        doc.embedder, doc.indexed_at = emb.name, datetime.now(UTC)
    return "ready"


async def _fail(tid: uuid.UUID, did: uuid.UUID, msg: str) -> str:
    async with tenant_session(tid) as s:
        doc = await s.get(AiDocument, did)
        if doc is not None:
            doc.status, doc.error = "failed", msg
    return "failed"


async def reindex_stale() -> int:
    """At worker start: re-index ready documents made by another embedder (e.g. the hashing fallback, once the real
    model could be downloaded), so vector search covers every document again."""
    from sqlalchemy import select, text

    from app.core.db import global_session

    name = get_embedder().name
    async with global_session() as s:  # tenant ids only (SECURITY DEFINER function for system jobs)
        tenants = list((await s.execute(text("SELECT * FROM erp_active_tenant_ids()"))).scalars())
    n = 0
    for tid in tenants:
        async with tenant_session(tid) as s:
            stale = list((await s.execute(select(AiDocument.id).where(
                AiDocument.deleted_at.is_(None), AiDocument.status == "ready", AiDocument.embedder != name
            ))).scalars())  # fmt: skip
        for did in stale:
            await ingest_document({}, str(tid), str(did))
            n += 1
    if n:
        log.info("re-indexed %d document(s) with %s", n, name)
    return n

"""Hybrid retrieval: pgvector (cosine, HNSW with iterative scan) + PostgreSQL full text, merged with Reciprocal Rank
Fusion. Both paths filter by company (RLS + explicit tenant) and by the document's roles BEFORE ranking, so a chunk the
user may not see never reaches the model. Retrieved text is untrusted data (the prompt says so)."""

import asyncio
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, Text, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import get_embedder
from app.ai.rag.models import AiDocument, AiDocumentChunk

K = 60  # RRF constant
CANDIDATES = 20
MIN_SIMILARITY = {"hash-384": 0.45}  # cosine similarity for a meaning-only match (bge-small: 0.6 default)
STOP = {"what", "does", "our", "the", "say", "says", "about", "and", "for", "with", "need", "this", "that", "how",
        "when", "who", "which", "are", "policy", "sop", "document", "procedure"}  # fmt: skip


@dataclass
class Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    page: int | None
    text: str
    score: float
    via: list[str]  # vector | keyword


def _visible(q: Select, tenant_id: uuid.UUID, role: str) -> Select:  # type: ignore[type-arg]
    return q.join(AiDocument, AiDocument.id == AiDocumentChunk.document_id).where(
        AiDocumentChunk.tenant_id == tenant_id, AiDocument.tenant_id == tenant_id, AiDocument.deleted_at.is_(None),
        AiDocument.status == "ready", or_(func.cardinality(AiDocument.roles) == 0, AiDocument.roles.contains([role])),
    )  # fmt: skip


async def search(session: AsyncSession, tenant_id: uuid.UUID, role: str, query: str, k: int = 5) -> list[Hit]:
    query = query.strip()[:500]
    if not query:
        return []
    emb = await asyncio.to_thread(get_embedder)  # never block the event loop while the model loads
    qv = (await asyncio.to_thread(emb.embed, [query]))[0]
    cols = (
        AiDocumentChunk.id,
        AiDocumentChunk.document_id,
        AiDocument.title,
        AiDocumentChunk.page,
        AiDocumentChunk.text,
    )
    # vector path: only chunks made by the embedder in use (different models' vectors aren't comparable)
    await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    sim = (1 - AiDocumentChunk.embedding.cosine_distance(qv)).label("sim")
    vq = _visible(select(*cols, sim), tenant_id, role).where(AiDocumentChunk.embedder == emb.name)
    vq = vq.order_by(AiDocumentChunk.embedding.cosine_distance(qv)).limit(CANDIDATES)
    vec = (await session.execute(vq)).all()
    # keyword path: exact words / identifiers (CNC-01, DIN 933, M12...)
    tsq = func.websearch_to_tsquery("english", query)
    or_q = func.to_tsquery(
        "english", func.regexp_replace(func.plainto_tsquery("english", query).cast(Text), "&", "|", "g")
    )
    kq = _visible(select(*cols), tenant_id, role).where(AiDocumentChunk.tsv.op("@@")(or_q))
    kq = kq.order_by(
        func.ts_rank_cd(AiDocumentChunk.tsv, or_q).desc(), func.ts_rank_cd(AiDocumentChunk.tsv, tsq).desc()
    ).limit(CANDIDATES)
    kw = (await session.execute(kq)).all()
    scores: dict[uuid.UUID, float] = {}
    rows: dict[uuid.UUID, tuple] = {}  # type: ignore[type-arg]
    via: dict[uuid.UUID, list[str]] = {}
    for name, ranked in (("vector", vec), ("keyword", kw)):
        for rank, r in enumerate(ranked):
            scores[r[0]] = scores.get(r[0], 0.0) + 1.0 / (K + rank + 1)
            rows[r[0]] = tuple(r)
            via.setdefault(r[0], []).append(name)
    # keep passages that share at least two of the question's words (ranked by both paths), else the single closest
    # one by meaning if it is close enough (a small library would otherwise return every chunk as "related")
    terms = {w for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", query.lower()) if len(w) > 2} - STOP
    need = min(2, len(terms))
    keep = {r[0] for r in kw if sum(t in r[4].lower() for t in terms) >= need}
    if not keep and vec and vec[0][5] >= MIN_SIMILARITY.get(emb.name, 0.6):
        keep = {
            vec[0][0]
        }  # nothing shares the question's words: the closest passage by meaning, if it is close
    best = sorted((c for c in scores if c in keep), key=lambda c: -scores[c])[:k]
    return [Hit(chunk_id=c, document_id=rows[c][1], title=rows[c][2], page=rows[c][3], text=rows[c][4],
                score=round(scores[c], 4), via=via[c]) for c in best]  # fmt: skip

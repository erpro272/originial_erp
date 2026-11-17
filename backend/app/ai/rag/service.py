"""Company documents for the assistant: upload (encrypted, then indexed by the worker), list, re-index, delete.
Who may see a document in answers = its roles (empty = every role); the uploader or the owner may change / delete it."""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.ingestion import IngestError, kind_of
from app.ai.rag.models import AiDocument, AiDocumentChunk
from app.ai.rag.schemas import AiDocumentOut
from app.core import audit, filetokens, keys
from app.core.auth import Principal
from app.core.errors import DomainError, Forbidden, NotFound
from app.core.permissions import Role
from app.core.storage import put_encrypted, tenant_key

MAX_BYTES = 20 * 1024 * 1024
CTYPE = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "txt": "text/plain"}  # fmt: skip
ROLES = {r.value for r in Role}


def _out(d: AiDocument, p: Principal) -> AiDocumentOut:
    return AiDocumentOut(id=d.id, title=d.title, file_name=d.file_name, size_bytes=d.size_bytes, roles=d.roles or [],
                       status=d.status, error=d.error, pages=d.pages, chunks=d.chunks, embedder=d.embedder,
                       created_at=d.created_at, indexed_at=d.indexed_at,
                       can_edit=d.uploaded_by == p.user_id or p.role == Role.OWNER,
                       url=f"/api/files/{filetokens.make(d.tenant_id, d.file_key)}")  # fmt: skip


def _check_roles(roles: list[str]) -> list[str]:
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise DomainError(f"Unknown role: {', '.join(bad)}.", details={"field": "roles"})
    return sorted(set(roles))


async def upload(session: AsyncSession, p: Principal, name: str, data: bytes, title: str | None,
                 roles: list[str]) -> AiDocumentOut:  # fmt: skip
    if len(data) > MAX_BYTES:
        raise DomainError("The file is larger than 20 MB.")
    if not data:
        raise DomainError("The file is empty.")
    try:
        kind = kind_of(name, data)
    except IngestError as exc:
        raise DomainError(str(exc)) from exc
    sha = hashlib.sha256(data).hexdigest()
    dup = (
        await session.execute(
            select(AiDocument).where(AiDocument.sha256 == sha, AiDocument.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise DomainError(
            f"This file is already uploaded as “{dup.title}”.", details={"document_id": str(dup.id)}
        )
    safe = (name or "document").replace("/", "_").replace("\\", "_")[:200]
    did = uuid.uuid4()
    cipher = await keys.get_cipher(session, p.tenant_id)
    key = tenant_key(p.tenant_id, "documents", str(did), f"original.{kind}")
    await put_encrypted(cipher, key, data)
    doc = AiDocument(id=did, title=(title or safe.rsplit(".", 1)[0]).strip()[:200], file_name=safe, file_key=key,
                     content_type=CTYPE[kind], size_bytes=len(data), sha256=sha, roles=_check_roles(roles),
                     status="queued", uploaded_by=p.user_id)  # fmt: skip
    session.add(doc)
    await session.flush()
    await audit.record(session, actor_id=p.user_id, action="upload", entity_type="ai_document", entity_id=did,
                       summary=f"Document '{doc.title}' uploaded for the AI Assistant")  # fmt: skip
    return _out(doc, p)


async def list_documents(session: AsyncSession, p: Principal) -> list[AiDocumentOut]:
    q = (select(AiDocument).where(AiDocument.deleted_at.is_(None))
         .where(or_(AiDocument.roles == [], AiDocument.roles.contains([str(p.role)]), AiDocument.uploaded_by == p.user_id))
         .order_by(AiDocument.created_at.desc()))  # fmt: skip
    return [_out(d, p) for d in (await session.execute(q)).scalars()]


async def _editable(session: AsyncSession, p: Principal, did: uuid.UUID) -> AiDocument:
    d = await session.get(AiDocument, did)
    if d is None or d.deleted_at is not None:
        raise NotFound("Document not found.")
    if d.uploaded_by != p.user_id and p.role != Role.OWNER:
        raise Forbidden("Only the person who uploaded it, or the owner, can change this document.")
    return d


async def update(
    session: AsyncSession, p: Principal, did: uuid.UUID, title: str | None, roles: list[str] | None
) -> AiDocumentOut:
    d = await _editable(session, p, did)
    before = {"title": d.title, "roles": d.roles}
    if title is not None:
        d.title = title.strip()[:200]
    if roles is not None:
        d.roles = _check_roles(roles)
    await audit.record(session, actor_id=p.user_id, action="update", entity_type="ai_document", entity_id=d.id,
                       summary=f"Document '{d.title}' updated", before=before, after={"title": d.title, "roles": d.roles})  # fmt: skip
    return _out(d, p)


async def reindex(session: AsyncSession, p: Principal, did: uuid.UUID) -> AiDocumentOut:
    d = await _editable(session, p, did)
    d.status, d.error = "queued", None
    return _out(d, p)


async def delete(session: AsyncSession, p: Principal, did: uuid.UUID) -> None:
    d = await _editable(session, p, did)
    d.deleted_at = datetime.now(UTC)
    await session.execute(
        sa_delete(AiDocumentChunk).where(AiDocumentChunk.document_id == did)
    )  # gone from answers now
    await audit.record(session, actor_id=p.user_id, action="delete", entity_type="ai_document", entity_id=d.id,
                       summary=f"Document '{d.title}' deleted")  # fmt: skip


async def link(session: AsyncSession, p: Principal, did: uuid.UUID) -> str:
    """A fresh 5-minute link to the original, only for a document this user may see (citations in old answers)."""
    d = await session.get(AiDocument, did)
    if d is None or d.deleted_at is not None:
        raise NotFound("This document was deleted.")
    if d.roles and str(p.role) not in d.roles and d.uploaded_by != p.user_id:
        raise NotFound("This document was deleted.")
    return f"/api/files/{filetokens.make(d.tenant_id, d.file_key)}"

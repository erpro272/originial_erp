import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile

from app.ai.rag import service
from app.ai.rag.schemas import AiDocumentOut, AiDocumentPatch
from app.core import jobs
from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission

router = APIRouter(prefix="/ai/documents", tags=["ai"])
User = Annotated[Principal, Depends(require(Permission.AI_USE))]


@router.get("", response_model=list[AiDocumentOut])
async def list_documents(db: TenantDB, p: User) -> list[AiDocumentOut]:
    return await service.list_documents(db, p)


@router.post("", response_model=AiDocumentOut, status_code=201)
async def upload(
    db: TenantDB,
    p: User,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF (with text), Word .docx, .txt or .md; up to 20 MB")],
    title: Annotated[str | None, Form()] = None,
    roles: Annotated[
        list[str] | None, Form(description="roles that may see it in answers; none = everyone")
    ] = None,
) -> AiDocumentOut:
    data = await file.read(service.MAX_BYTES + 1)
    doc = await service.upload(db, p, file.filename or "document", data, title, [r for r in roles or [] if r])
    background.add_task(jobs.enqueue, "ingest_document", str(p.tenant_id), str(doc.id))  # after the commit
    return doc


@router.get("/{did}/link")
async def link(did: uuid.UUID, db: TenantDB, p: User) -> dict[str, str]:
    """A fresh short-lived link to the original (citations open the cited page with it)."""
    return {"url": await service.link(db, p, did)}


@router.patch("/{did}", response_model=AiDocumentOut)
async def update(did: uuid.UUID, body: AiDocumentPatch, db: TenantDB, p: User) -> AiDocumentOut:
    return await service.update(db, p, did, body.title, body.roles)


@router.post("/{did}/reindex", response_model=AiDocumentOut)
async def reindex(did: uuid.UUID, db: TenantDB, p: User, background: BackgroundTasks) -> AiDocumentOut:
    doc = await service.reindex(db, p, did)
    background.add_task(jobs.enqueue, "ingest_document", str(p.tenant_id), str(did))
    return doc


@router.delete("/{did}", status_code=204)
async def delete(did: uuid.UUID, db: TenantDB, p: User) -> None:
    await service.delete(db, p, did)

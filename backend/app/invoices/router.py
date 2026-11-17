import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.core import filetokens, jobs, keys
from app.core.auth import Principal, TenantDB, require
from app.core.crypto import mask_tail
from app.core.db import tenant_session
from app.core.errors import DomainError, NotFound
from app.core.permissions import Permission
from app.core.storage import get_decrypted
from app.invoices import fields, service
from app.invoices.files import MAX_BYTES
from app.invoices.models import (
    Invoice,
    InvoiceLine,
    InvoiceParty,
    InvoicePayment,
    InvoiceTransport,
    InvoiceUpload,
)
from app.invoices.schemas import (
    BatchOut,
    CheckResult,
    Draft,
    DraftSave,
    RejectIn,
    SaveIn,
    SaveOut,
    UploadDetail,
    UploadList,
    UploadOut,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])
files_router = APIRouter(tags=["files"])
Writer = Annotated[Principal, Depends(require(Permission.INVOICES_WRITE))]
Reader = Annotated[Principal, Depends(require(Permission.CUSTOMERS_READ))]


@router.get("/field-spec")
async def field_spec(_: Reader) -> dict[str, Any]:
    """Appendix A sections and fields, for rendering the verification screen."""
    return fields.public_spec()


@router.post("/uploads", status_code=201)
async def upload(
    db: TenantDB,
    p: Writer,
    background: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="JPG, PNG, HEIC or PDF; up to 20 MB each, 25 files")],
) -> BatchOut:
    incoming = []
    for f in files:
        data = await f.read(MAX_BYTES + 1)
        incoming.append((f.filename or "invoice", data))
    batch = await service.create_uploads(db, p.user_id, p.tenant_id, incoming)
    for u in batch.uploads:  # runs after the response, i.e. after the commit
        background.add_task(jobs.enqueue, "extract_invoice", str(p.tenant_id), str(u.id))
    return batch


@router.get("/uploads")
async def list_uploads(
    db: TenantDB,
    _: Writer,
    status: Annotated[list[str] | None, Query()] = None,
    batch_id: uuid.UUID | None = None,
) -> UploadList:
    return await service.list_uploads(db, status, batch_id)


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: uuid.UUID, db: TenantDB, p: Writer) -> UploadDetail:
    return await service.get_detail(db, upload_id, p.can(Permission.SENSITIVE_VIEW))


@router.post("/uploads/{upload_id}/check")
async def check(
    upload_id: uuid.UUID, body: Draft, db: TenantDB, _: Writer, customer_id: uuid.UUID | None = None
) -> CheckResult:
    """Run every check on the user's current edits without saving anything."""
    return await service.check_draft(db, upload_id, body, customer_id)


@router.put("/uploads/{upload_id}/draft")
async def save_draft(upload_id: uuid.UUID, body: DraftSave, db: TenantDB, p: Writer) -> UploadOut:
    return await service.save_draft(db, p.user_id, upload_id, body, body.verified)


@router.post("/uploads/{upload_id}/save")
async def save(upload_id: uuid.UUID, body: SaveIn, db: TenantDB, p: Writer) -> SaveOut:
    return await service.save(db, p.user_id, upload_id, body)


@router.post("/uploads/{upload_id}/reject")
async def reject(upload_id: uuid.UUID, body: RejectIn, db: TenantDB, p: Writer) -> UploadOut:
    return await service.reject(db, p.user_id, upload_id, body.reason)


@router.post("/uploads/{upload_id}/retry")
async def retry(upload_id: uuid.UUID, db: TenantDB, p: Writer, background: BackgroundTasks) -> UploadOut:
    u = await service.mark_for_retry(db, upload_id)
    background.add_task(jobs.enqueue, "extract_invoice", str(p.tenant_id), str(u.id))
    return await service._out(db, u)


class InvoiceView(BaseModel):
    invoice: dict[str, Any]
    parties: list[dict[str, Any]]
    lines: list[dict[str, Any]]
    payment: dict[str, Any] | None
    transport: dict[str, Any] | None
    original_url: str | None
    upload_id: uuid.UUID | None


def _row(obj: Any, skip: set[str] | None = None) -> dict[str, Any]:
    out = {}
    for c in obj.__table__.columns:
        if c.name in (skip or set()) or c.name == "tenant_id":
            continue
        val = getattr(obj, c.name)
        out[c.name] = (
            str(val)
            if isinstance(val, uuid.UUID | Decimal)
            else val.isoformat()
            if isinstance(val, date | datetime)
            else val
        )
    return out


@router.get("/{invoice_id}")
async def get_invoice(invoice_id: uuid.UUID, db: TenantDB, p: Reader) -> InvoiceView:
    inv = await db.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("Invoice not found.")
    parties = (await db.execute(select(InvoiceParty).where(InvoiceParty.invoice_id == inv.id))).scalars()
    lines = (
        await db.execute(
            select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)
        )
    ).scalars()
    pay = (
        await db.execute(select(InvoicePayment).where(InvoicePayment.invoice_id == inv.id))
    ).scalar_one_or_none()
    tr = (
        await db.execute(select(InvoiceTransport).where(InvoiceTransport.invoice_id == inv.id))
    ).scalar_one_or_none()
    payment = None
    if pay:
        cipher = await keys.get_cipher(db, inv.tenant_id)
        visible = p.can(Permission.SENSITIVE_VIEW)
        acct = cipher.decrypt(pay.bank_account_enc, "invoice.bank_account") if pay.bank_account_enc else None
        upi = cipher.decrypt(pay.upi_enc, "invoice.upi_id") if pay.upi_enc else None
        payment = _row(pay, {"bank_account_enc", "upi_enc"}) | {
            "bank_account": acct if visible else mask_tail(acct), "upi_id": upi if visible else mask_tail(upi),
            "sensitive_visible": visible,
        }  # fmt: skip
    original = None
    if inv.upload_id and (u := await db.get(InvoiceUpload, inv.upload_id)):
        original = f"/api/files/{filetokens.make(inv.tenant_id, u.file_key)}"
    return InvoiceView(invoice=_row(inv), parties=[_row(x) for x in parties], lines=[_row(x) for x in lines],
                       payment=payment, transport=_row(tr) if tr else None, original_url=original,
                       upload_id=inv.upload_id)  # fmt: skip


@files_router.get("/files/{token}", response_class=Response)
async def get_file(token: str) -> Response:
    """Short-lived signed link (no session needed, so <img src> works). 5-minute expiry."""
    ok = filetokens.verify(token)
    if ok is None:
        raise DomainError("This link has expired. Reload the page.")
    tenant_id, key = ok
    async with tenant_session(tenant_id) as s:
        cipher = await keys.get_cipher(s, tenant_id)
    try:
        data = await get_decrypted(cipher, key)
    except Exception as exc:
        raise NotFound("File not found.") from exc
    ext = key.rsplit(".", 1)[-1].lower()
    ctype = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "pdf": "application/pdf",
        "heic": "image/heic",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8",
    }.get(ext, "application/octet-stream")
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=300",
                                                     "X-Content-Type-Options": "nosniff",
                                                     "Content-Disposition": "inline"})  # fmt: skip

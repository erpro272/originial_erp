"""Invoice upload pipeline: upload -> extract (worker) -> review -> match -> save.

Statuses: uploaded -> extracting -> needs_review -> verified -> saved (+ failed, rejected).
Nothing is saved to the ERP automatically: saving needs the user's explicit action.
"""

import base64
import hashlib
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, clock, events, filetokens, keys
from app.core.crypto import TenantCipher, mask_tail
from app.core.errors import Conflict, DomainError, NotFound
from app.core.gst import financial_year, is_valid_gstin, state_code_from_gstin
from app.core.models import User
from app.core.storage import put_encrypted, tenant_key
from app.customers import service as customers
from app.invoices import checks as chk
from app.invoices import dupes, files, matching
from app.invoices.fields import SENSITIVE_FIELDS
from app.invoices.models import (
    ExtractionRun,
    Invoice,
    InvoiceLine,
    InvoiceParty,
    InvoicePayment,
    InvoiceReceipt,
    InvoiceTransport,
    InvoiceUpload,
)
from app.invoices.normalize import apply_edits, dec, lv, overall_confidence, v
from app.invoices.schemas import (
    BatchOut,
    CheckResult,
    Draft,
    PageOut,
    RejectedFile,
    SaveIn,
    SaveOut,
    UploadDetail,
    UploadList,
    UploadOut,
)

MAX_FILES = 25
REVIEWABLE = ("needs_review", "verified")


# ---- sensitive values inside the extraction document ---------------------------------------


def seal(doc: dict[str, Any], cipher: TenantCipher) -> dict[str, Any]:
    """Encrypt bank account / UPI values before the document is stored (Layer 2)."""
    out = {**doc, "fields": dict(doc["fields"])}
    for key in SENSITIVE_FIELDS:
        cell = out["fields"].get(key)
        if cell and cell.get("raw"):
            enc = base64.b64encode(cipher.encrypt(cell["raw"], f"invoice.{key}")).decode()
            out["fields"][key] = {**cell, "raw": None, "value": None, "enc": enc}
    return out


def unseal(doc: dict[str, Any], cipher: TenantCipher, visible: bool = True) -> dict[str, Any]:
    out = {**doc, "fields": dict(doc["fields"])}
    for key in SENSITIVE_FIELDS:
        cell = out["fields"].get(key)
        if cell and cell.get("enc"):
            plain = cipher.decrypt(base64.b64decode(cell["enc"]), f"invoice.{key}")
            shown = plain if visible else mask_tail(plain)
            out["fields"][key] = {k: x for k, x in cell.items() if k != "enc"} | {"raw": shown, "value": shown,
                                                                                    "masked": not visible}  # fmt: skip
    return out


# ---- reading -------------------------------------------------------------------------------


async def _out(session: AsyncSession, u: InvoiceUpload, doc: dict[str, Any] | None = None) -> UploadOut:
    name = (
        await session.execute(select(User.full_name).where(User.id == u.uploaded_by))
    ).scalar_one_or_none()
    o = UploadOut(
        id=u.id, batch_id=u.batch_id, file_name=u.file_name, doc_format=u.doc_format, size_bytes=u.size_bytes,
        page_count=u.page_count, status=u.status, error=u.error,
        overall_confidence=float(u.overall_confidence) if u.overall_confidence is not None else None,
        duplicate_flag=u.duplicate_flag, ai_mode=u.ai_mode, customer_action=u.customer_action, invoice_id=u.invoice_id,
        uploaded_by_name=name, created_at=u.created_at,
    )  # fmt: skip
    if doc:
        o.buyer_name, o.invoice_number, o.grand_total_paise = (
            v(doc, "buyer_name"),
            v(doc, "invoice_number"),
            v(doc, "grand_total"),
        )
    return o


async def _latest(session: AsyncSession, upload_id: uuid.UUID) -> ExtractionRun | None:
    return (
        await session.execute(
            select(ExtractionRun)
            .where(ExtractionRun.upload_id == upload_id)
            .order_by(ExtractionRun.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _upload(session: AsyncSession, upload_id: uuid.UUID, lock: bool = False) -> InvoiceUpload:
    u = await session.get(InvoiceUpload, upload_id, with_for_update=lock)
    if u is None:
        raise NotFound("Upload not found.")
    return u


async def list_uploads(
    session: AsyncSession, status: list[str] | None, batch_id: uuid.UUID | None
) -> UploadList:
    q = select(InvoiceUpload).order_by(InvoiceUpload.created_at.desc()).limit(500)
    if status:
        q = q.where(InvoiceUpload.status.in_(status))
    if batch_id:
        q = q.where(InvoiceUpload.batch_id == batch_id)
    uploads = list((await session.execute(q)).scalars())
    cipher = await keys.get_cipher(session, uploads[0].tenant_id) if uploads else None
    items = []
    for u in uploads:
        run = await _latest(session, u.id)
        items.append(await _out(session, u, unseal(run.data, cipher, False) if run and cipher else None))
    counts = dict(
        (
            await session.execute(select(InvoiceUpload.status, func.count()).group_by(InvoiceUpload.status))
        ).all()
    )
    scope = items
    summary = {
        "imported": sum(i.status == "saved" for i in scope),
        "matched_existing": sum(i.customer_action == "existing" for i in scope),
        "new_customers": sum(i.customer_action == "new" for i in scope),
        "need_review": sum(i.status in REVIEWABLE for i in scope),
        "processing": sum(i.status in ("uploaded", "extracting") for i in scope),
        "failed": sum(i.status == "failed" for i in scope),
    }
    return UploadList(items=items, counts=counts, summary=summary)


async def _evaluate(
    session: AsyncSession, doc: dict[str, Any], customer_id: uuid.UUID | None = None
) -> tuple[list[chk.Check], matching.MatchResult, dupes.Duplicate]:
    m = await matching.match_customer(session, doc)
    d = await dupes.find_duplicate(session, doc, customer_id or m.customer_id)
    checks = chk.run_checks(doc, clock.today())
    if d.flag == "exact":
        checks.append(
            chk.Check("duplicate", "error", "fields.invoice_number", d.message or "Duplicate invoice.")
        )
    elif d.flag == "possible":
        checks.append(chk.Check("possible_duplicate", "warning", "fields.invoice_number", d.message or ""))
    return checks, m, d


async def get_detail(session: AsyncSession, upload_id: uuid.UUID, can_see_sensitive: bool) -> UploadDetail:
    u = await _upload(session, upload_id)
    run = await _latest(session, u.id)
    cipher = await keys.get_cipher(session, u.tenant_id)
    doc = unseal(run.data, cipher, True) if run else None
    if doc:
        checks, m, d = await _evaluate(session, doc)
        shown = unseal(run.data, cipher, can_see_sensitive)  # type: ignore[union-attr]
    else:
        checks, m, d, shown = [], None, dupes.Duplicate("none"), {"fields": {}, "lines": [], "qr": None}
    versions = (
        await session.execute(select(func.count()).where(ExtractionRun.upload_id == u.id))
    ).scalar_one()
    return UploadDetail(
        upload=await _out(session, u, doc),
        pages=[PageOut(number=i + 1, url=f"/api/files/{filetokens.make(u.tenant_id, k)}") for i, k in enumerate(u.page_keys)],
        original_url=f"/api/files/{filetokens.make(u.tenant_id, u.file_key)}",
        document=shown, checks=[c.to_dict() for c in checks], match=m.to_dict() if m else {},
        duplicate=d.to_dict(), versions=versions, sensitive_visible=can_see_sensitive,
    )  # fmt: skip


# ---- upload --------------------------------------------------------------------------------


async def create_uploads(session: AsyncSession, actor: uuid.UUID, tenant_id: uuid.UUID,
                         incoming: list[tuple[str, bytes]]) -> BatchOut:  # fmt: skip
    if not incoming:
        raise DomainError("Choose at least one file.")
    if len(incoming) > MAX_FILES:
        raise DomainError(f"Upload at most {MAX_FILES} files at a time.")
    batch = uuid.uuid4()
    created, rejected = [], []
    cipher = await keys.get_cipher(session, tenant_id)
    for name, data in incoming:
        safe_name = (name or "invoice").replace("/", "_").replace("\\", "_")[:200]
        try:
            det = files.detect(data)
        except files.UnsupportedFile as exc:
            rejected.append(RejectedFile(file_name=safe_name, error=str(exc)))
            continue
        uid = uuid.uuid4()
        key = tenant_key(tenant_id, "invoices", str(uid), f"original.{det.ext}")
        await put_encrypted(cipher, key, data)
        u = InvoiceUpload(id=uid, batch_id=batch, file_key=key, file_name=safe_name, content_type=det.content_type,
                          size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), doc_format=det.doc_format,
                          uploaded_by=actor, status="uploaded")  # fmt: skip
        session.add(u)
        created.append(u)
    await session.flush()
    for u in created:
        await audit.record(session, actor_id=actor, action="upload", entity_type="invoice_upload", entity_id=u.id,
                           summary=f"Invoice file '{u.file_name}' uploaded")  # fmt: skip
    return BatchOut(batch_id=batch, uploads=[await _out(session, u) for u in created], rejected=rejected)


# ---- review --------------------------------------------------------------------------------


async def check_draft(
    session: AsyncSession, upload_id: uuid.UUID, draft: Draft, customer_id: uuid.UUID | None
) -> CheckResult:
    u = await _upload(session, upload_id)
    run = await _latest(session, u.id)
    if run is None:
        raise DomainError("This file hasn't been read yet.")
    cipher = await keys.get_cipher(session, u.tenant_id)
    doc = apply_edits(unseal(run.data, cipher), draft.fields, draft.lines)
    checks, m, d = await _evaluate(session, doc, customer_id)
    return CheckResult(
        document=doc, checks=[c.to_dict() for c in checks], match=m.to_dict(), duplicate=d.to_dict()
    )


async def save_draft(
    session: AsyncSession, actor: uuid.UUID, upload_id: uuid.UUID, draft: Draft, verified: bool
) -> UploadOut:
    u = await _upload(session, upload_id, lock=True)
    if u.status not in REVIEWABLE:
        raise DomainError(f"This upload is {u.status.replace('_', ' ')} and can't be edited.")
    run = await _latest(session, u.id)
    assert run is not None
    cipher = await keys.get_cipher(session, u.tenant_id)
    doc = apply_edits(unseal(run.data, cipher), draft.fields, draft.lines)
    if verified:
        checks, _, _ = await _evaluate(session, doc)
        if chk.blocking(checks):
            raise DomainError("Fix the errors before marking this invoice as verified.",
                              details={"checks": [c.to_dict() for c in chk.blocking(checks)]})  # fmt: skip
    session.add(
        ExtractionRun(
            upload_id=u.id, version=run.version + 1, source="user", data=seal(doc, cipher), created_by=actor
        )
    )
    u.status = "verified" if verified else "needs_review"
    u.overall_confidence = (
        Decimal(str(overall_confidence(doc))) if overall_confidence(doc) is not None else None
    )
    return await _out(session, u, doc)


async def reject(session: AsyncSession, actor: uuid.UUID, upload_id: uuid.UUID, reason: str) -> UploadOut:
    u = await _upload(session, upload_id, lock=True)
    if u.status == "saved":
        raise DomainError("This invoice is already saved.")
    u.status, u.error = "rejected", reason
    await audit.record(session, actor_id=actor, action="reject", entity_type="invoice_upload", entity_id=u.id,
                       summary=f"'{u.file_name}' rejected: {reason}")  # fmt: skip
    return await _out(session, u)


async def mark_for_retry(session: AsyncSession, upload_id: uuid.UUID) -> InvoiceUpload:
    u = await _upload(session, upload_id, lock=True)
    if u.status not in ("failed", "needs_review"):
        raise DomainError("Only failed or unreviewed uploads can be read again.")
    u.status, u.error = "uploaded", None
    return u


# ---- save ----------------------------------------------------------------------------------


async def save(session: AsyncSession, actor: uuid.UUID, upload_id: uuid.UUID, body: SaveIn) -> SaveOut:
    """One transaction: customer (new or existing), invoice + parties + lines + payment +
    transport, order link, extraction version, audit, invoice.created event."""
    u = await _upload(session, upload_id, lock=True)
    if u.status not in REVIEWABLE:
        raise DomainError(f"This upload is {u.status.replace('_', ' ')} and can't be saved.")
    run = await _latest(session, u.id)
    assert run is not None
    cipher = await keys.get_cipher(session, u.tenant_id)
    doc = apply_edits(unseal(run.data, cipher), body.fields, body.lines)

    choice = body.customer
    if choice.mode == "existing":
        if not choice.customer_id:
            raise DomainError("Choose the customer to attach this invoice to.")
        if not any(c.id == choice.customer_id for c in await customers.active_customers(session)):
            raise NotFound("That customer doesn't exist (or was merged).")
    elif choice.customer is None:
        raise DomainError("Fill in the new customer's details.")

    checks, _, dup = await _evaluate(session, doc, choice.customer_id if choice.mode == "existing" else None)
    errors = chk.blocking(checks)
    if errors:
        raise DomainError("Fix the errors before saving.", details={"checks": [c.to_dict() for c in errors]})
    pending = [
        c for c in chk.unacknowledged(checks, set(body.acknowledged)) if c.code != "possible_duplicate"
    ]
    if pending:
        raise DomainError(
            "Review and accept the warnings before saving.",
            details={"checks": [c.to_dict() for c in pending]},
        )
    if dup.flag == "possible" and not body.confirm_possible_duplicate:
        raise Conflict(dup.message or "Possible duplicate.", details={"duplicate": dup.to_dict()})

    if choice.mode == "new":
        assert choice.customer is not None
        cust = await customers.create_customer(session, actor, choice.customer, source="invoice")
        customer_id = cust.id
    else:
        assert choice.customer_id is not None
        customer_id = choice.customer_id
        await customers.fill_missing_from_invoice(session, customer_id, matching.prefill(doc))

    inv = _invoice_from_doc(doc, customer_id, u)
    session.add(inv)
    await session.flush()
    _children(session, inv, doc, cipher)
    from app.orders import service as orders

    order = await orders.find_order_for_invoice(
        session, customer_id, [(lv(ln, "product_name"), dec(lv(ln, "quantity"))) for ln in doc["lines"]]
    )
    inv.order_id = order.id if order else None
    session.add(
        ExtractionRun(
            upload_id=u.id, version=run.version + 1, source="user", data=seal(doc, cipher), created_by=actor
        )
    )
    u.status, u.invoice_id, u.customer_action, u.duplicate_flag = "saved", inv.id, choice.mode, dup.flag
    await audit.record(session, actor_id=actor, action="create", entity_type="invoice", entity_id=inv.id,
                       summary=f"Invoice {inv.invoice_number} saved from '{u.file_name}'"
                               + (f" (linked to {order.number})" if order else ""),
                       after={"customer_id": str(customer_id), "grand_total_paise": inv.grand_total_paise,
                              "acknowledged_warnings": sorted(body.acknowledged)})  # fmt: skip
    await events.emit(session, "invoice.created", {
        "invoice_id": str(inv.id), "customer_id": str(customer_id), "invoice_date": str(inv.invoice_date),
        "grand_total_paise": inv.grand_total_paise, "balance_due_paise": inv.balance_due_paise,
    })  # fmt: skip
    return SaveOut(invoice_id=inv.id, customer_id=customer_id, customer_action=choice.mode,
                   order_number=order.number if order else None)  # fmt: skip


def _d(x: Any) -> date | None:
    return date.fromisoformat(x) if x else None


def _invoice_from_doc(doc: dict[str, Any], customer_id: uuid.UUID, u: InvoiceUpload) -> Invoice:
    inv_date = _d(v(doc, "invoice_date"))
    seller, buyer = v(doc, "seller_gstin"), v(doc, "buyer_gstin")
    seller_state = (
        v(doc, "seller_state_code")
        or v(doc, "seller_state")
        or (state_code_from_gstin(seller) if seller and is_valid_gstin(seller) else None)
    )
    pos = v(doc, "place_of_supply") or v(doc, "buyer_state_code") or v(doc, "buyer_state")
    gt = v(doc, "grand_total")
    balance = v(doc, "balance_due")
    if balance is None and gt is not None:
        balance = gt - (v(doc, "amount_paid") or 0) - (v(doc, "advance_received") or 0)
    return Invoice(
        upload_id=u.id, customer_id=customer_id, source="upload",
        invoice_number=v(doc, "invoice_number"), invoice_date=inv_date, invoice_type=v(doc, "invoice_type"),
        due_date=_d(v(doc, "due_date")), original_invoice_ref=v(doc, "original_invoice_ref"), irn=v(doc, "irn"),
        ack_no=v(doc, "ack_no"), ack_date=_d(v(doc, "ack_date")),
        financial_year=financial_year(inv_date) if inv_date else None,
        seller_gstin=seller, buyer_gstin=buyer,
        subtotal_paise=v(doc, "subtotal"), total_quantity=dec(v(doc, "total_quantity")),
        total_discount_paise=v(doc, "total_discount"), total_taxable_paise=v(doc, "total_taxable"),
        total_cgst_paise=v(doc, "total_cgst"), total_sgst_paise=v(doc, "total_sgst"),
        total_igst_paise=v(doc, "total_igst"), total_cess_paise=v(doc, "total_cess"),
        freight_paise=v(doc, "freight"), packing_paise=v(doc, "packing"), other_charges_paise=v(doc, "other_charges"),
        round_off_paise=v(doc, "round_off"), grand_total_paise=gt, amount_in_words=v(doc, "amount_in_words"),
        amount_paid_paise=v(doc, "amount_paid"), advance_received_paise=v(doc, "advance_received"),
        balance_due_paise=balance,
        reverse_charge=v(doc, "reverse_charge"), place_of_supply=doc["fields"]["place_of_supply"]["raw"],
        place_of_supply_code=v(doc, "place_of_supply"), state_of_supply=doc["fields"]["state_of_supply"]["raw"],
        supply_type=("intra" if seller_state == pos else "inter") if seller_state and pos else None,
        delivery_terms=v(doc, "delivery_terms"), payment_terms_conditions=v(doc, "payment_terms_conditions"),
        warranty=v(doc, "warranty"), declaration=v(doc, "declaration"),
        authorised_signatory=v(doc, "authorised_signatory"),
        digital_signature_present=v(doc, "digital_signature_present"),
        digital_signature_name=v(doc, "digital_signature_name"), qr_data=doc.get("qr"),
        duplicate_flag="none", overall_confidence=Decimal(str(c)) if (c := overall_confidence(doc)) is not None else None,
    )  # fmt: skip


def _children(session: AsyncSession, inv: Invoice, doc: dict[str, Any], cipher: TenantCipher) -> None:
    paid = (inv.grand_total_paise or 0) - (inv.balance_due_paise or 0)
    if paid > 0 and inv.grand_total_paise:  # what the invoice says was paid becomes a receipt (Billing)
        session.add(InvoiceReceipt(invoice_id=inv.id, kind="opening", amount_paise=paid,
                                   received_on=inv.invoice_date or clock.today(),
                                   note="Paid as shown on the uploaded invoice"))  # fmt: skip
    for role in ("seller", "buyer"):
        session.add(InvoiceParty(
            invoice_id=inv.id, role=role, name=v(doc, f"{role}_name"), gstin=v(doc, f"{role}_gstin"),
            pan=v(doc, f"{role}_pan"),
            address=v(doc, "seller_address") if role == "seller" else v(doc, "buyer_billing_address"),
            shipping_address=v(doc, "buyer_shipping_address") if role == "buyer" else None,
            state=doc["fields"][f"{role}_state"]["raw"], state_code=v(doc, f"{role}_state_code") or v(doc, f"{role}_state"),
            contact_person=v(doc, "buyer_contact_person") if role == "buyer" else None,
            phone=v(doc, f"{role}_phone"), email=v(doc, f"{role}_email"),
        ))  # fmt: skip
    for i, ln in enumerate(doc["lines"], start=1):
        session.add(InvoiceLine(
            invoice_id=inv.id, line_no=i, product_name=lv(ln, "product_name"), description=lv(ln, "description"),
            sku=lv(ln, "sku"), hsn=lv(ln, "hsn"), quantity=dec(lv(ln, "quantity")), uom=lv(ln, "uom"),
            unit_price_paise=lv(ln, "unit_price"), discount_pct=dec(lv(ln, "discount_pct")),
            discount_paise=lv(ln, "discount_amount"), taxable_paise=lv(ln, "taxable_value"),
            gst_rate=dec(lv(ln, "gst_rate")), cgst_paise=lv(ln, "cgst"), sgst_paise=lv(ln, "sgst"),
            igst_paise=lv(ln, "igst"), cess_paise=lv(ln, "cess"), total_paise=lv(ln, "total"),
        ))  # fmt: skip
    account, upi = v(doc, "bank_account_number"), v(doc, "upi_id")
    payment_keys = ("payment_terms", "payment_mode", "bank_name", "bank_ifsc", "utr", "cheque_number")
    if account or upi or any(v(doc, k) for k in payment_keys):
        digits = "".join(ch for ch in (account or "") if ch.isdigit())
        session.add(InvoicePayment(
            invoice_id=inv.id, payment_terms=v(doc, "payment_terms"), payment_mode=v(doc, "payment_mode"),
            bank_name=v(doc, "bank_name"), bank_ifsc=(v(doc, "bank_ifsc") or "")[:11] or None,
            bank_account_enc=cipher.encrypt(account, "invoice.bank_account") if account else None,
            bank_account_last4=digits[-4:] or None, upi_enc=cipher.encrypt(upi, "invoice.upi_id") if upi else None,
            utr=v(doc, "utr"), cheque_no=v(doc, "cheque_number"),
        ))  # fmt: skip
    tkeys = ("transporter_name", "transporter_id", "vehicle_number", "lr_number", "eway_bill_number", "eway_bill_date",
             "dispatch_date", "delivery_date", "transport_mode", "place_of_dispatch", "place_of_delivery")  # fmt: skip
    if any(v(doc, k) for k in tkeys):
        session.add(InvoiceTransport(
            invoice_id=inv.id, transporter_name=v(doc, "transporter_name"), transporter_id=v(doc, "transporter_id"),
            vehicle_no=v(doc, "vehicle_number"), lr_no=v(doc, "lr_number"), eway_bill_no=v(doc, "eway_bill_number"),
            eway_bill_date=_d(v(doc, "eway_bill_date")), dispatch_date=_d(v(doc, "dispatch_date")),
            delivery_date=_d(v(doc, "delivery_date")), mode=v(doc, "transport_mode"),
            place_of_dispatch=v(doc, "place_of_dispatch"), place_of_delivery=v(doc, "place_of_delivery"),
        ))  # fmt: skip

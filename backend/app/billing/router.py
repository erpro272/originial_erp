import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.billing import deals, payables, receivables
from app.billing.schemas import (
    ApInvoice,
    ApOut,
    ApSupplier,
    ArCustomer,
    ArOut,
    BankConfirmIn,
    DealCreateIn,
    DealDetail,
    DealEditIn,
    DealsOut,
    DraftEditIn,
    ExecuteIn,
    FollowUpIn,
    InteractionIn,
    InteractionOut,
    PromiseIn,
    ReasonIn,
    ReceiptIn,
    ScheduleIn,
    SendIn,
    SupplierInvoiceIn,
)
from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission

router = APIRouter(prefix="/billing", tags=["billing"])
Reader = Annotated[Principal, Depends(require(Permission.BILLING_READ))]
Writer = Annotated[Principal, Depends(require(Permission.BILLING_WRITE))]
Issuer = Annotated[Principal, Depends(require(Permission.BILLING_ISSUE))]
Owner = Annotated[Principal, Depends(require(Permission.BILLING_APPROVE))]
Month = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")]


def _csv(text: str, name: str) -> Response:
    return Response(
        text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


# ---- receivables ------------------------------------------------------------------------------------


@router.get("/receivables")
async def get_receivables(db: TenantDB, _: Reader, month: Month = None, q: str | None = None,
                          status: str | None = None) -> ArOut:  # fmt: skip
    """Cards + one row per customer, as of the end of `month` (or today)."""
    return await receivables.receivables(db, month, q, status)


@router.get("/receivables/export", response_class=Response)
async def export_receivables(db: TenantDB, p: Reader, month: Month = None, q: str | None = None,
                             status: str | None = None) -> Response:  # fmt: skip
    return _csv(await receivables.export_csv(db, p.user_id, month, q, status), "receivables.csv")


@router.get("/receivables/customers/{customer_id}")
async def receivable_customer(
    db: TenantDB, _: Reader, customer_id: uuid.UUID, month: Month = None
) -> ArCustomer:
    return await receivables.customer(db, customer_id, month)


@router.post("/receivables/customers/{customer_id}/follow-ups", status_code=201)
async def follow_up(db: TenantDB, p: Writer, customer_id: uuid.UUID, body: FollowUpIn) -> InteractionOut:
    return await receivables.log_follow_up(db, p.user_id, customer_id, body)


@router.post("/receivables/invoices/{invoice_id}/promises", status_code=201)
async def promise(db: TenantDB, p: Writer, invoice_id: uuid.UUID, body: PromiseIn) -> ArCustomer:
    """Update commitment: a new promise row; older ones are kept."""
    return await receivables.add_promise(db, p.user_id, invoice_id, body)


@router.post("/receivables/invoices/{invoice_id}/receipts", status_code=201)
async def receipt(db: TenantDB, p: Writer, invoice_id: uuid.UUID, body: ReceiptIn) -> ArCustomer:
    """Money received (or an advance adjusted / a credit note): outstanding is recomputed."""
    return await receivables.add_receipt(db, p.user_id, invoice_id, body)


# ---- payables ---------------------------------------------------------------------------------------


@router.get("/payables")
async def get_payables(db: TenantDB, _: Reader, month: Month = None, q: str | None = None,
                       status: str | None = None) -> ApOut:  # fmt: skip
    return await payables.payables(db, month, q, status)


@router.get("/payables/export", response_class=Response)
async def export_payables(db: TenantDB, p: Reader, month: Month = None, q: str | None = None,
                          status: str | None = None) -> Response:  # fmt: skip
    return _csv(await payables.export_csv(db, p.user_id, month, q, status), "payables.csv")


@router.get("/payables/suppliers/{supplier_id}")
async def payable_supplier(
    db: TenantDB, _: Reader, supplier_id: uuid.UUID, month: Month = None
) -> ApSupplier:
    return await payables.supplier(db, supplier_id, month)


@router.post("/payables/invoices", status_code=201)
async def add_supplier_invoice(db: TenantDB, p: Writer, body: SupplierInvoiceIn) -> ApInvoice:
    """A supplier invoice arrives: linked to its PO and purchase deal; the three-way match runs."""
    return await payables.create(db, p.user_id, body)


@router.post("/payables/invoices/{invoice_id}/verify")
async def verify(db: TenantDB, p: Writer, invoice_id: uuid.UUID) -> ApInvoice:
    """Accounts verification (three-way match must agree)."""
    return await payables.verify(db, p.user_id, invoice_id)


@router.post("/payables/invoices/{invoice_id}/approve")
async def approve(db: TenantDB, p: Owner, invoice_id: uuid.UUID) -> ApInvoice:
    """Owner approval: a decision, separate from scheduling and paying."""
    return await payables.approve(db, p.user_id, invoice_id)


@router.post("/payables/invoices/{invoice_id}/schedule")
async def schedule(db: TenantDB, p: Writer, invoice_id: uuid.UUID, body: ScheduleIn) -> ApInvoice:
    return await payables.schedule(db, p.user_id, invoice_id, body)


@router.post("/payables/invoices/{invoice_id}/{action}")
async def hold(db: TenantDB, p: Owner, invoice_id: uuid.UUID, action: Literal["hold", "reject", "release"],
               body: ReasonIn) -> ApInvoice:  # fmt: skip
    """Owner: hold or reject (cancels scheduled payments), or release a hold (back to approval)."""
    if action == "release":
        return await payables.release(db, p.user_id, invoice_id, body.reason)
    return await payables.hold_or_reject(db, p.user_id, invoice_id, action, body.reason)


@router.post("/payables/payments/{payment_id}/execute")
async def execute(db: TenantDB, p: Writer, payment_id: uuid.UUID, body: ExecuteIn) -> ApInvoice:
    """Sent from the bank (UTR). The approver can't also execute, unless the owner overrides with a reason."""
    return await payables.execute(db, p.user_id, p.can(Permission.BILLING_APPROVE), payment_id, body)


@router.post("/payables/payments/{payment_id}/bank-confirm")
async def bank_confirm(db: TenantDB, p: Writer, payment_id: uuid.UUID, body: BankConfirmIn) -> ApInvoice:
    """The bank statement line matches (UTR, amount): only now the payment counts."""
    return await payables.bank_confirm(db, p.user_id, payment_id, body)


# ---- deals (Invoice / E-bill) ---------------------------------------------------------------------------


@router.get("/deals")
async def list_deals(db: TenantDB, _: Reader, month: Annotated[str | None, Query()] = None) -> DealsOut:
    """Every deal with KPIs (for `month`, or all months)."""
    return await deals.list_deals(db, month)


@router.post("/deals", status_code=201)
async def create_deal(db: TenantDB, p: Writer, body: DealCreateIn) -> DealDetail:
    """A provisional deal from an enquiry; refuses a duplicate reference, warns on a look-alike."""
    return await deals.create(db, p.user_id, body)


@router.get("/deals/{deal_id}")
async def get_deal(db: TenantDB, _: Reader, deal_id: uuid.UUID) -> DealDetail:
    return await deals.detail(db, deal_id)


@router.patch("/deals/{deal_id}")
async def edit_deal(db: TenantDB, p: Writer, deal_id: uuid.UUID, body: DealEditIn) -> DealDetail:
    return await deals.edit(db, p.user_id, deal_id, body)


@router.post("/deals/{deal_id}/archive")
async def archive_deal(db: TenantDB, p: Writer, deal_id: uuid.UUID) -> DealDetail:
    return await deals.archive(db, p.user_id, deal_id)


@router.post("/deals/{deal_id}/interactions", status_code=201)
async def add_interaction(db: TenantDB, p: Writer, deal_id: uuid.UUID, body: InteractionIn) -> InteractionOut:
    return await deals.add_interaction(db, p.user_id, deal_id, body)


@router.post("/deals/{deal_id}/invoice")
async def generate_invoice(db: TenantDB, p: Writer, deal_id: uuid.UUID) -> DealDetail:
    """A draft from the shipped order (never counted as issued)."""
    return await deals.generate_invoice(db, p.user_id, deal_id)


@router.patch("/deals/{deal_id}/invoice")
async def edit_draft(db: TenantDB, p: Writer, deal_id: uuid.UUID, body: DraftEditIn) -> DealDetail:
    return await deals.edit_draft(db, p.user_id, deal_id, body)


@router.post("/deals/{deal_id}/invoice/verify")
async def verify_invoice(db: TenantDB, p: Writer, deal_id: uuid.UUID) -> DealDetail:
    return await deals.verify_invoice(db, p.user_id, deal_id)


@router.post("/deals/{deal_id}/invoice/issue")
async def issue_invoice(db: TenantDB, p: Issuer, deal_id: uuid.UUID) -> DealDetail:
    """Number, lock, receivable and event, in one transaction (owner or accountant)."""
    return await deals.issue_invoice(db, p.user_id, deal_id)


@router.post("/deals/{deal_id}/invoice/send")
async def send_invoice(db: TenantDB, p: Writer, deal_id: uuid.UUID, body: SendIn) -> DealDetail:
    return await deals.send_invoice(db, p.user_id, deal_id, body)


@router.get("/deal-refs")
async def deal_refs(db: TenantDB, _: Reader, order_id: Annotated[list[uuid.UUID] | None, Query()] = None,
                    po_id: Annotated[list[uuid.UUID] | None, Query()] = None) -> dict[str, dict[str, str]]:  # fmt: skip
    """Order / PO id -> its deal (id, TXN number): the chips on Orders and Purchasing screens."""
    refs = await deals.deal_refs(db, order_ids=order_id, po_ids=po_id)
    return {str(k): {"id": str(v[0]), "number": v[1]} for k, v in refs.items()}

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Channel = Literal["call", "whatsapp", "email", "visit", "meeting"]


# ---- receivables ---------------------------------------------------------------------------------


class Period(BaseModel):
    month: str  # YYYY-MM
    start: date
    as_of: date  # end of the month, or today for the current one
    live: bool  # the current period: follow-ups and commitments can be changed


class ArCards(BaseModel):
    total_paise: int
    total_customers: int
    total_invoices: int
    overdue_paise: int
    overdue_customers: int
    oldest_overdue_days: int | None
    expected_week_paise: int
    week_from: date
    week_to: date
    received_paise: int  # cash receipts in the period (advances adjusted are not new cash)
    receipts: int


ArStatus = Literal["overdue", "due_week", "promise", "not_due"]


class ArRow(BaseModel):
    customer_id: uuid.UUID
    name: str
    gstin: str | None
    phone: str | None
    outstanding_paise: int
    open_invoices: int
    earliest_due: date | None
    days_overdue: int  # of the earliest due, if past
    status: ArStatus
    part_paid: bool
    has_promise: bool = False  # an open invoice has a promise on record
    latest_update: str | None
    latest_at: date | None


class ArOut(BaseModel):
    period: Period
    cards: ArCards
    rows: list[ArRow]
    counts: dict[str, int]  # all | overdue | due_week | promise | part_paid


class PromiseOut(BaseModel):
    amount_paise: int
    promised_on: date
    note: str | None
    at: datetime
    by: str | None


class ReceiptOut(BaseModel):
    id: uuid.UUID
    kind: str
    amount_paise: int
    received_on: date
    method: str | None
    reference: str | None
    note: str | None
    by: str | None


class InteractionOut(BaseModel):
    id: uuid.UUID
    channel: str
    direction: str
    contact: str | None
    summary: str
    next_follow_up: date | None
    invoice_number: str | None
    deal_number: str | None
    at: datetime
    by: str | None


class ArInvoice(BaseModel):
    id: uuid.UUID
    number: str | None
    invoice_date: date | None
    due_date: date | None  # original, contractual: never changes after issue
    total_paise: int
    received_paise: int
    outstanding_paise: int
    days_overdue: int
    promised_on: date | None  # the latest promise
    expected_on: date | None  # promised date, else the due date
    status: ArStatus
    part_paid: bool
    deal_id: uuid.UUID | None
    deal_number: str | None
    promises: list[PromiseOut]
    receipts: list[ReceiptOut]


class ArCustomer(BaseModel):
    customer_id: uuid.UUID
    name: str
    gstin: str | None
    phone: str | None
    email: str | None
    city: str | None
    payment_terms_days: int | None
    period: Period
    invoices: list[ArInvoice]  # open as of the period end
    interactions: list[InteractionOut]


class ArFollowUpIn(BaseModel):
    invoice_id: uuid.UUID | None = None
    channel: Channel
    direction: Literal["incoming", "outgoing"] = "outgoing"
    contact: str | None = Field(default=None, max_length=200)
    note: str = Field(min_length=1, max_length=2000)
    next_follow_up: date | None = None


class PromiseIn(BaseModel):
    amount_paise: int = Field(gt=0)
    promised_on: date
    note: str | None = Field(default=None, max_length=2000)


class ReceiptIn(BaseModel):
    kind: Literal["receipt", "advance", "credit_note"] = "receipt"
    amount_paise: int = Field(gt=0)
    received_on: date
    method: Literal["neft", "rtgs", "imps", "upi", "cheque", "cash"] | None = None
    reference: str | None = Field(default=None, max_length=64)  # UTR / cheque no.
    note: str | None = Field(default=None, max_length=2000)


# ---- payables ------------------------------------------------------------------------------------

ApStatus = Literal["pending_verif", "pending_owner", "approved", "scheduled", "paid", "on_hold", "rejected"]


class MatchLine(BaseModel):
    check: str  # supplier | quantity | rate | amount
    ok: bool
    text: str


class ApPayment(BaseModel):
    id: uuid.UUID
    amount_paise: int
    scheduled_for: date
    status: str  # scheduled | executed | confirmed | cancelled
    utr: str | None
    executed_on: date | None
    confirmed_on: date | None
    override_reason: str | None


class ApEvent(BaseModel):
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    at: datetime
    by: str | None


class ApInvoice(BaseModel):
    id: uuid.UUID
    number: str
    supplier_id: uuid.UUID
    supplier: str
    po_id: uuid.UUID | None
    po_number: str | None
    grn: str | None  # the gate entries of the PO
    deal_id: uuid.UUID | None
    deal_number: str | None
    invoice_date: date
    due_date: date
    quantity: Decimal
    unit: str | None
    rate_paise: int
    taxable_paise: int
    gst_paise: int
    total_paise: int
    paid_paise: int  # bank-confirmed only
    scheduled_paise: int  # planned, not paid
    outstanding_paise: int
    days_overdue: int
    status: ApStatus
    stage: int  # 1-7 on the approval stepper
    match: list[MatchLine]
    match_ok: bool
    hold_reason: str | None
    payments: list[ApPayment] = []
    events: list[ApEvent] = []


class ApCards(BaseModel):
    total_paise: int
    total_suppliers: int
    total_invoices: int
    overdue_paise: int
    overdue_suppliers: int
    due_week_paise: int
    week_from: date
    week_to: date
    paid_paise: int  # executed in the period
    payments: int


class ApRow(BaseModel):
    supplier_id: uuid.UUID
    name: str
    gstin: str | None
    outstanding_paise: int
    invoices: int
    disputed_paise: int  # rejected (out of the total)
    earliest_due: date | None
    days_overdue: int
    statuses: list[ApStatus]
    overdue: bool
    due_week: bool


class ApOut(BaseModel):
    period: Period
    cards: ApCards
    rows: list[ApRow]
    counts: dict[str, int]


class ApSupplier(BaseModel):
    supplier_id: uuid.UUID
    name: str
    gstin: str | None
    period: Period
    invoices: list[ApInvoice]
    interactions: list[InteractionOut]


class SupplierInvoiceIn(BaseModel):
    po_id: uuid.UUID
    number: str = Field(min_length=1, max_length=64)
    invoice_date: date
    due_date: date | None = None  # default: invoice date + 30 days
    quantity: Decimal = Field(gt=0)
    rate_paise: int = Field(gt=0)
    gst_rate: Decimal = Field(default=Decimal(18), ge=0, le=28)
    supplier_gstin: str | None = Field(default=None, max_length=15)
    note: str | None = Field(default=None, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ScheduleIn(BaseModel):
    amount_paise: int = Field(gt=0)
    scheduled_for: date


class ExecuteIn(BaseModel):
    utr: str = Field(min_length=4, max_length=40)
    executed_on: date
    override_reason: str | None = Field(default=None, max_length=2000)  # owner executing their own approval


class BankConfirmIn(BaseModel):
    utr: str = Field(min_length=4, max_length=40)
    amount_paise: int = Field(gt=0)
    confirmed_on: date


# ---- deals ---------------------------------------------------------------------------------------


class DealRow(BaseModel):
    id: uuid.UUID
    number: str
    kind: Literal["sale", "purchase"]
    name: str
    reference: str | None
    company_id: uuid.UUID | None
    company: str
    documents: int
    latest_activity: str | None
    latest_at: datetime | None
    latest_direction: str | None
    value_paise: int | None
    status: str
    provisional: bool
    archived: bool


class DealKpis(BaseModel):
    active: int
    total: int
    awaiting_response: int
    documents_received: int
    invoices_issued: int


class DealsOut(BaseModel):
    kpis: DealKpis
    rows: list[DealRow]
    companies: list[str]
    statuses: list[str]


class DocumentOut(BaseModel):
    """A document of the deal: a view of the record that owns it (order, PO, gate entry, invoice, receipt...)."""

    key: str
    kind: (
        str  # customer_po | sales_order | purchase_order | grn | qc | sales_invoice | supplier_invoice | ...
    )
    name: str
    number: str | None
    direction: Literal["incoming", "outgoing", "internal"]
    status: str
    date: date | None
    amount_paise: int | None
    source: str  # Orders | Purchasing | Invoice / E-bill | Payments


class ActivityOut(BaseModel):
    at: datetime
    title: str
    direction: Literal["incoming", "outgoing", "internal"]
    source: str
    by: str | None
    milestone: bool
    document_key: str | None


class InvoiceCard(BaseModel):
    id: uuid.UUID
    number: str | None
    status: str  # draft | verified | issued | sent
    invoice_date: date | None
    due_date: date | None
    quantity: Decimal | None
    rate_paise: int | None
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    other_charges_paise: int
    total_paise: int
    received_paise: int
    outstanding_paise: int
    payment_terms_days: int | None
    verified_at: datetime | None
    issued_at: datetime | None
    sent_at: datetime | None


class DealDetail(BaseModel):
    row: DealRow
    customer_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    order_id: uuid.UUID | None
    po_id: uuid.UUID | None
    item: str | None
    quantity: Decimal | None
    unit: str | None
    dispatched_qty: Decimal | None  # sale: the order quantity once shipped
    received_qty: Decimal | None  # purchase: QC accepted
    payment_terms_days: int | None
    billing_basis: str
    contact: str | None
    note: str | None
    on_hold: bool
    hold_reason: str | None
    cancelled_reason: str | None
    created_at: datetime
    ship_date: date | None
    invoice: InvoiceCard | None
    invoice_block: str | None  # why an invoice can't be raised now
    payable: ApInvoice | None
    documents: list[DocumentOut]
    interactions: list[InteractionOut]
    activity: list[ActivityOut]


class DealCreateIn(BaseModel):
    kind: Literal["sale", "purchase"]
    company: str = Field(min_length=1, max_length=200)  # customer or supplier name (existing)
    item: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(default=None, max_length=64)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=16)
    expected_value_paise: int | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    contact: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    force: bool = False  # create anyway after a "looks like a duplicate" warning


class DealEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    expected_value_paise: int | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)


class InteractionIn(BaseModel):
    channel: Channel
    direction: Literal["incoming", "outgoing"] = "outgoing"
    contact: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    next_follow_up: date | None = None


class DraftEditIn(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0)
    rate_paise: int | None = Field(default=None, gt=0)
    other_charges_paise: int | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)


class SendIn(BaseModel):
    channel: Literal["email", "whatsapp"]
    contact: str | None = Field(default=None, max_length=200)

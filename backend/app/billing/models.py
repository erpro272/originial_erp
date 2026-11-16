"""Billing: deals (the TXN-#### spine), what happened on them, follow-ups and promises on receivables, and the
supplier-invoice workflow (payables).

Canonical records stay where they are owned: orders (Orders), POs / gate entries / QC (Purchasing), sales
invoices and their receipts (Invoices). Billing links to them and never copies a total.
Append-only (insert-only for the app role): deal_events, interactions, payment_promises, payable_events.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin

DEAL_STATUSES = (
    "Enquiry Received", "Quotation in Progress", "Negotiation", "Awaiting Response", "Quotation Accepted",
    "Order Confirmed", "Processing", "Partially Dispatched", "Dispatched", "Invoice Pending", "Invoiced",
    "Partially Settled", "Completed", "On Hold", "Cancelled",
)  # fmt: skip


class Deal(Base, TenantScoped, TimestampMixin):
    """One sale or purchase from first contact to settlement. Status is derived from the linked records
    (`status` keeps the last derivation so lists can filter on it); the Deal ID is permanent."""

    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        UniqueConstraint("tenant_id", "order_id"),
        UniqueConstraint("tenant_id", "po_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(16))  # TXN-1001
    kind: Mapped[str] = mapped_column(String(8))  # sale | purchase
    name: Mapped[str] = mapped_column(String(200))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    reference: Mapped[str | None] = mapped_column(String(64))  # ORD-, PO-, ENQ-...
    reference_kind: Mapped[str | None] = mapped_column(String(16))  # order | po | enquiry
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)  # from an enquiry, no order yet
    item: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))
    unit: Mapped[str | None] = mapped_column(String(16))
    expected_value_paise: Mapped[int | None] = mapped_column(BigInteger)  # provisional deals only
    payment_terms_days: Mapped[int | None]
    billing_basis: Mapped[str] = mapped_column(
        String(16), default="consolidated"
    )  # per_dispatch | consolidated
    contact: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="Order Confirmed", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class DealEvent(Base, TenantScoped):
    """Something Billing did or decided on a deal (created, invoice draft / verified / issued / sent, hold...).
    Events of other modules (order, PO, gate entry, receipts) are read from their own records, not copied."""

    __tablename__ = "deal_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(10), default="internal")  # incoming | outgoing | internal
    milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Interaction(Base, TenantScoped):
    """A call, WhatsApp, email, visit or meeting with a customer / supplier. Logged from Payments (follow-ups)
    or from a deal; the same record shows in both."""

    __tablename__ = "interactions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    supplier_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("supplier_invoices.id"))
    channel: Mapped[str] = mapped_column(String(12))  # call | whatsapp | email | visit | meeting
    direction: Mapped[str] = mapped_column(String(10), default="outgoing")  # incoming | outgoing
    contact: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    next_follow_up: Mapped[date | None]
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentPromise(Base, TenantScoped):
    """What a customer says they will pay and when. A change is a new row; older ones are kept."""

    __tablename__ = "payment_promises"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    promised_on: Mapped[date]
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# pending_verif -> pending_owner (accounts verified, three-way match clean) -> approved (owner) -> scheduled
# -> paid (every rupee executed and bank-confirmed). on_hold / rejected (owner, with a reason) from any
# open stage; release hold -> pending_owner. Rejected invoices are disputed: out of the payables total.
SUPPLIER_INVOICE_STATUSES = (
    "pending_verif",
    "pending_owner",
    "approved",
    "scheduled",
    "paid",
    "on_hold",
    "rejected",
)


class SupplierInvoice(Base, TenantScoped, TimestampMixin):
    __tablename__ = "supplier_invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id"), index=True)
    number: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date]
    due_date: Mapped[date]
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 3))  # billed
    rate_paise: Mapped[int] = mapped_column(BigInteger)  # per unit
    taxable_paise: Mapped[int] = mapped_column(BigInteger)
    gst_paise: Mapped[int] = mapped_column(BigInteger)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    supplier_gstin: Mapped[str | None] = mapped_column(String(15))
    status: Mapped[str] = mapped_column(String(16), default="pending_verif", index=True)
    match: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # three-way match at entry / verify
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    hold_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class SupplierPayment(Base, TenantScoped, TimestampMixin):
    """scheduled (a plan: never reduces the outstanding) -> executed (sent from the bank, UTR) -> confirmed
    (matched on the bank statement: only now it counts) | cancelled (hold / reject)."""

    __tablename__ = "supplier_payments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    supplier_invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_invoices.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    scheduled_for: Mapped[date]
    status: Mapped[str] = mapped_column(String(12), default="scheduled")
    utr: Mapped[str | None] = mapped_column(String(40))
    executed_on: Mapped[date | None]
    executed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_on: Mapped[date | None]
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    scheduled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    override_reason: Mapped[str | None] = mapped_column(Text)  # owner executing their own approval


class PayableEvent(Base, TenantScoped):
    """Approval history of a supplier invoice: who, when, from, to, note."""

    __tablename__ = "payable_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    supplier_invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_invoices.id"), index=True)
    action: Mapped[str] = mapped_column(String(24))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

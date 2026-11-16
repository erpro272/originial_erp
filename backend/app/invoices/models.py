"""Invoice tables (Appendix A, normalised) and the upload/extraction pipeline records."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin

UPLOAD_STATUSES = (
    "uploaded", "extracting", "needs_review", "verified", "saved", "failed", "rejected",
)  # fmt: skip
DUPLICATE_FLAGS = ("none", "possible", "exact")

Paise = BigInteger


class InvoiceUpload(Base, TenantScoped, TimestampMixin):
    """One uploaded file and its trip through the pipeline (Section 9 metadata)."""

    __tablename__ = "invoice_uploads"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(index=True)
    file_key: Mapped[str] = mapped_column(String(300))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    doc_format: Mapped[str] = mapped_column(String(8))  # image | pdf
    page_count: Mapped[int | None] = mapped_column(SmallInteger)
    page_keys: Mapped[list[str]] = mapped_column(ARRAY(String(300)), default=list)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="uploaded", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    qr_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    duplicate_flag: Mapped[str] = mapped_column(String(8), default="none")
    duplicate_of_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", use_alter=True, name="fk_invoice_uploads_dup_invoice")
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", use_alter=True, name="fk_invoice_uploads_invoice")
    )
    ai_mode: Mapped[str | None] = mapped_column(String(8))  # live | mock
    customer_action: Mapped[str | None] = mapped_column(String(10))  # existing | new (on save)


class ExtractionRun(Base, TenantScoped):
    """Versioned extraction record: v1 = raw model output, later versions = user corrections."""

    __tablename__ = "extraction_runs"
    __table_args__ = (UniqueConstraint("upload_id", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoice_uploads.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    source: Mapped[str] = mapped_column(String(8))  # model | user
    model: Mapped[str | None] = mapped_column(String(64))
    raw_output: Mapped[str | None] = mapped_column(
        Text
    )  # exact model text, encrypted (may hold bank details)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(Base, TenantScoped, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_customer_date", "customer_id", "invoice_date"),
        Index(
            "uq_invoices_seller_number_fy",
            "tenant_id", "seller_gstin", "invoice_number", "financial_year",
            unique=True,
            postgresql_where=text("seller_gstin IS NOT NULL AND invoice_number IS NOT NULL"),
        ),
        Index("uq_invoices_irn", "tenant_id", "irn", unique=True,
              postgresql_where=text("irn IS NOT NULL")),
    )  # fmt: skip
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_uploads.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    source: Mapped[str] = mapped_column(String(12), default="upload")  # upload | seed | billing
    # 1. identification
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    invoice_date: Mapped[date | None]
    invoice_type: Mapped[str | None] = mapped_column(String(40))
    due_date: Mapped[date | None]
    original_invoice_ref: Mapped[str | None] = mapped_column(String(64))
    irn: Mapped[str | None] = mapped_column(String(64))
    ack_no: Mapped[str | None] = mapped_column(String(32))
    ack_date: Mapped[date | None]
    financial_year: Mapped[str | None] = mapped_column(String(7))
    seller_gstin: Mapped[str | None] = mapped_column(String(15))  # denormalised for dup checks
    buyer_gstin: Mapped[str | None] = mapped_column(String(15))
    # 5. financial summary (paise)
    subtotal_paise: Mapped[int | None] = mapped_column(Paise)
    total_quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))
    total_discount_paise: Mapped[int | None] = mapped_column(Paise)
    total_taxable_paise: Mapped[int | None] = mapped_column(Paise)
    total_cgst_paise: Mapped[int | None] = mapped_column(Paise)
    total_sgst_paise: Mapped[int | None] = mapped_column(Paise)
    total_igst_paise: Mapped[int | None] = mapped_column(Paise)
    total_cess_paise: Mapped[int | None] = mapped_column(Paise)
    freight_paise: Mapped[int | None] = mapped_column(Paise)
    packing_paise: Mapped[int | None] = mapped_column(Paise)
    other_charges_paise: Mapped[int | None] = mapped_column(Paise)
    round_off_paise: Mapped[int | None] = mapped_column(Paise)
    grand_total_paise: Mapped[int | None] = mapped_column(Paise)
    amount_in_words: Mapped[str | None] = mapped_column(Text)
    # 6. payment amounts (details in invoice_payments)
    amount_paid_paise: Mapped[int | None] = mapped_column(Paise)
    advance_received_paise: Mapped[int | None] = mapped_column(Paise)
    balance_due_paise: Mapped[int | None] = mapped_column(Paise)
    # 8. additional information
    reverse_charge: Mapped[bool | None] = mapped_column(Boolean)
    place_of_supply: Mapped[str | None] = mapped_column(String(100))
    place_of_supply_code: Mapped[str | None] = mapped_column(String(2))
    state_of_supply: Mapped[str | None] = mapped_column(String(100))
    supply_type: Mapped[str | None] = mapped_column(String(5))  # intra | inter
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    payment_terms_conditions: Mapped[str | None] = mapped_column(Text)
    warranty: Mapped[str | None] = mapped_column(Text)
    declaration: Mapped[str | None] = mapped_column(Text)
    authorised_signatory: Mapped[str | None] = mapped_column(String(200))
    digital_signature_present: Mapped[bool | None] = mapped_column(Boolean)
    digital_signature_name: Mapped[str | None] = mapped_column(String(200))
    qr_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 9. metadata
    duplicate_flag: Mapped[str] = mapped_column(String(8), default="none")
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    # Billing (sales invoices raised in the app). NULL = an invoice issued outside (imported / seed).
    # draft -> verified -> issued -> sent. A draft is never a receivable; issued invoices are locked.
    billing_status: Mapped[str | None] = mapped_column(String(10), index=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # Billing's deal (TXN-####)
    payment_terms_days: Mapped[int | None]
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceParty(Base, TenantScoped):
    __tablename__ = "invoice_parties"
    __table_args__ = (UniqueConstraint("invoice_id", "role"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(8))  # seller | buyer
    name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(100))
    state_code: Mapped[str | None] = mapped_column(String(2))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))


class InvoiceLine(Base, TenantScoped):
    __tablename__ = "invoice_lines"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(64))
    hsn: Mapped[str | None] = mapped_column(String(16))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))
    uom: Mapped[str | None] = mapped_column(String(16))
    unit_price_paise: Mapped[int | None] = mapped_column(Paise)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    discount_paise: Mapped[int | None] = mapped_column(Paise)
    taxable_paise: Mapped[int | None] = mapped_column(Paise)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cgst_paise: Mapped[int | None] = mapped_column(Paise)
    sgst_paise: Mapped[int | None] = mapped_column(Paise)
    igst_paise: Mapped[int | None] = mapped_column(Paise)
    cess_paise: Mapped[int | None] = mapped_column(Paise)
    total_paise: Mapped[int | None] = mapped_column(Paise)


class InvoicePayment(Base, TenantScoped):
    __tablename__ = "invoice_payments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), unique=True)
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    payment_mode: Mapped[str | None] = mapped_column(String(60))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Layer 2
    bank_account_last4: Mapped[str | None] = mapped_column(String(4))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    upi_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Layer 2
    utr: Mapped[str | None] = mapped_column(String(64))
    cheque_no: Mapped[str | None] = mapped_column(String(32))


class InvoiceTransport(Base, TenantScoped):
    __tablename__ = "invoice_transport"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), unique=True)
    transporter_name: Mapped[str | None] = mapped_column(String(200))
    transporter_id: Mapped[str | None] = mapped_column(String(20))
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    lr_no: Mapped[str | None] = mapped_column(String(40))
    eway_bill_no: Mapped[str | None] = mapped_column(String(20))
    eway_bill_date: Mapped[date | None]
    dispatch_date: Mapped[date | None]
    delivery_date: Mapped[date | None]
    mode: Mapped[str | None] = mapped_column(String(20))
    place_of_dispatch: Mapped[str | None] = mapped_column(String(200))
    place_of_delivery: Mapped[str | None] = mapped_column(String(200))


# What an invoice receives: cash receipts, advances adjusted, credit notes, and the opening balance of what was
# paid before Billing existed. Outstanding = grand total - these (always computed). Insert-only for the app.
RECEIPT_KINDS = ("receipt", "advance", "credit_note", "opening")
CASH_KINDS = ("receipt", "opening")  # real money in; advances adjusted are not new cash


class InvoiceReceipt(Base, TenantScoped):
    __tablename__ = "invoice_receipts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    amount_paise: Mapped[int] = mapped_column(Paise)
    received_on: Mapped[date] = mapped_column(index=True)
    method: Mapped[str | None] = mapped_column(String(20))  # neft | rtgs | upi | cheque | cash
    reference: Mapped[str | None] = mapped_column(String(64))  # UTR / cheque no.
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

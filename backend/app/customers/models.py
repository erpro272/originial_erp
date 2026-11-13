import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin

TIERS = ("key", "standard", "occasional")
FOLLOWUP_KINDS = ("call", "whatsapp", "email", "note", "reminder")


class Customer(Base, TenantScoped, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        # GSTIN unique per company (ignoring customers merged away).
        Index(
            "uq_customers_tenant_gstin",
            "tenant_id",
            "gstin",
            unique=True,
            postgresql_where=text("gstin IS NOT NULL AND merged_into_id IS NULL"),
        ),
        Index("ix_customers_name_lower", text("lower(name)")),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    state_code: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    payment_terms_days: Mapped[int | None]
    credit_limit_paise: Mapped[int | None] = mapped_column(BigInteger)
    tier: Mapped[str] = mapped_column(String(16), default="standard")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    bank_account_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Layer 2
    bank_account_last4: Mapped[str | None] = mapped_column(String(4))
    upi_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Layer 2
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | invoice
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))


class CustomerAddress(Base, TenantScoped):
    __tablename__ = "customer_addresses"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # billing | shipping
    line1: Mapped[str] = mapped_column(String(300))
    line2: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    state_code: Mapped[str | None] = mapped_column(String(2))
    pincode: Mapped[str | None] = mapped_column(String(10))


class CustomerContact(Base, TenantScoped):
    __tablename__ = "customer_contacts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomerFollowup(Base, TenantScoped):
    __tablename__ = "customer_followups"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None]
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

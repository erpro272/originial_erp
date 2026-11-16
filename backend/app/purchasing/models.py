"""Purchasing: suppliers, purchase orders and the stock ledger.

Stock on hand is the sum of `stock_movements` (opening balance, receipts, issues, adjustments); the
`material_stock` row keeps that total and the next delivery on order, for the screens that read it
(Planning, Orders). Incoming = lines of POs that are ordered or confirmed (not yet fully received).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin

# awaiting_approval -> (owner approves) ordered ("PO sent") -> confirmed (supplier's date) -> dispatched
# (in transit) -> at_gate (gate entry logged, waiting for QC) -> received (QC accepted everything)
# A partial QC sends it back to confirmed / ordered for the rest. Open (not at the gate, nothing received)
# -> cancelled (with a reason).
PO_STATUSES = ("awaiting_approval", "ordered", "confirmed", "dispatched", "at_gate", "received", "cancelled")
OPEN = ("awaiting_approval", "ordered", "confirmed", "dispatched", "at_gate")
INCOMING = ("ordered", "confirmed", "dispatched", "at_gate")  # really on the way (approved and sent)


class Supplier(Base, TenantScoped, TimestampMixin):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))


class PurchaseOrder(Base, TenantScoped, TimestampMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32))  # PO-0001
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(String(24), default="awaiting_approval", index=True)
    expected_date: Mapped[date]  # asked for when raised; the supplier's date once confirmed
    confirmed: Mapped[bool] = mapped_column(default=False)  # expected_date confirmed by the supplier
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | planning
    raised_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    # orders the material is for (order numbers): from Planning's requests, or picked when raised by hand
    order_numbers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    priority: Mapped[str | None] = mapped_column(String(8))  # only for POs with no linked order
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # the gate entry waiting for QC (one at a time)
    gate_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    gate_ref: Mapped[str | None] = mapped_column(String(100))  # challan / vehicle no.
    gate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # the date the supplier committed to (at approval, then their first confirmation): on-time is judged
    # against it, so later follow-ups that move expected_date don't make a late delivery look on time
    promised_date: Mapped[date | None]


class PurchaseOrderLine(Base, TenantScoped, TimestampMixin):
    __tablename__ = "purchase_order_lines"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16))
    price_per_unit_paise: Mapped[int] = mapped_column(BigInteger)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))  # QC accepted
    rejected_qty: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0")
    )  # QC rejected (returned)


class StockMovement(Base, TenantScoped):
    """The stock ledger: on hand = sum of quantities. Insert-only for the app role."""

    __tablename__ = "stock_movements"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))  # + in, - out
    kind: Mapped[str] = mapped_column(String(16))  # opening | receipt | issue | adjustment
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order_lines.id"))
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PoEvent(Base, TenantScoped):
    """What happened to a PO, in order (raised, approved, confirmed, dispatched, gate entry, QC, follow-up,
    cancelled). Insert-only for the app role."""

    __tablename__ = "po_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierQuote(Base, TenantScoped, TimestampMixin):
    """A quote asked from a supplier for a material (requested), and their reply (received)."""

    __tablename__ = "supplier_quotes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="requested")  # requested | received
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    rate_paise: Mapped[int | None] = mapped_column(BigInteger)  # per unit
    lead_days: Mapped[int | None]
    valid_until: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PreferredSupplier(Base, TenantScoped, TimestampMixin):
    """The supplier chosen for a material (Select vendor): Raise PO pre-fills it."""

    __tablename__ = "preferred_suppliers"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    set_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

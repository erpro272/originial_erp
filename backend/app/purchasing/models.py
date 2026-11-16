"""Purchasing: suppliers, purchase orders and the stock ledger.

Stock on hand is the sum of `stock_movements` (opening balance, receipts, issues, adjustments); the
`material_stock` row keeps that total and the next delivery on order, for the screens that read it
(Planning, Orders). Incoming = lines of POs that are ordered or confirmed (not yet fully received).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin

# awaiting_approval -> (owner approves) ordered -> confirmed (supplier's date) -> received
# any open status -> cancelled (with a reason)
PO_STATUSES = ("awaiting_approval", "ordered", "confirmed", "received", "cancelled")
OPEN = ("awaiting_approval", "ordered", "confirmed")
INCOMING = ("ordered", "confirmed")  # really on the way (approved and sent)


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


class PurchaseOrderLine(Base, TenantScoped, TimestampMixin):
    __tablename__ = "purchase_order_lines"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16))
    price_per_unit_paise: Mapped[int] = mapped_column(BigInteger)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))


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

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScoped, TimestampMixin

PRIORITIES = ("high", "medium", "low")
STATUSES = ("new", "accepted", "planned", "in_production", "completed", "shipped", "cancelled")
CURRENT_STATUSES = ("new", "accepted", "planned", "in_production")
PAST_STATUSES = ("completed", "shipped", "cancelled")

# Allowed manual status changes (Planning/Production will drive some of these later).
TRANSITIONS: dict[str, set[str]] = {
    "new": {"accepted", "cancelled"},
    "accepted": {"new", "planned", "cancelled"},
    "planned": {"accepted", "in_production", "cancelled"},
    "in_production": {"completed"},
    "completed": {"shipped"},
    "shipped": set(),
    "cancelled": set(),
}


class Order(Base, TenantScoped, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32))  # ORD-1042
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16), default="pcs")
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    sales_paise: Mapped[int] = mapped_column(BigInteger)
    cost_paise: Mapped[int] = mapped_column(BigInteger)
    processing_days: Mapped[int]
    ship_date: Mapped[date] = mapped_column(index=True)
    priority: Mapped[str] = mapped_column(String(8), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    progress_pct: Mapped[int | None] = mapped_column(SmallInteger)
    marked_for_planning: Mapped[bool] = mapped_column(Boolean, default=False)
    promised_date: Mapped[date | None]
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def profit_paise(self) -> int:
        return self.sales_paise - self.cost_paise

"""Factory data the planner needs, plans, plan history and purchase requests."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin


class Department(Base, TenantScoped, TimestampMixin):
    """A labour pool (e.g. Machining). Machines draw operators from it."""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    hours_per_day: Mapped[Decimal] = mapped_column(Numeric(8, 2))  # labour hours available per day
    cost_per_hour_paise: Mapped[int] = mapped_column(BigInteger)


class Machine(Base, TenantScoped, TimestampMixin):
    __tablename__ = "machines"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"))
    hours_per_shift: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    shifts_per_day: Mapped[int] = mapped_column(default=1)
    operators: Mapped[int] = mapped_column(default=1)
    cost_per_hour_paise: Mapped[int] = mapped_column(BigInteger)  # machine + power
    night_shift_cost_per_hour_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    sort: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # QC / inspection stations: not counted when looking for idle production capacity.
    inspection: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class RouteStep(Base, TenantScoped):
    """How a product is made: machine steps in order."""

    __tablename__ = "route_steps"
    __table_args__ = (UniqueConstraint("product_id", "seq"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int]
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"))
    setup_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal(0))
    minutes_per_unit: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class Downtime(Base, TenantScoped):
    """Maintenance (machine set) or factory holiday (machine empty) on one day."""

    __tablename__ = "downtime"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(index=True)
    hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # None = the whole day
    reason: Mapped[str | None] = mapped_column(String(200))


PLAN_STATUSES = ("draft", "generated", "approved")


class Plan(Base, TenantScoped, TimestampMixin):
    """One working plan at a time. `inputs` = what the owner chose; `result` = what the engine computed."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32))  # PLAN-001
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    needs_reapproval: Mapped[bool] = mapped_column(Boolean, default=False)
    rule: Mapped[str] = mapped_column(String(16), default="deadline")
    start_date: Mapped[date]
    selected: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # order ids (str)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # sequence, locks, pins, fixes
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fingerprint: Mapped[str | None] = mapped_column(String(64))  # of everything the result depends on
    options_fingerprint: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=0)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approval_note: Mapped[str | None] = mapped_column(Text)


class PlanEvent(Base, TenantScoped):
    """The plan's history log (Tab 5)."""

    __tablename__ = "plan_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    tabs: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # tabs whose numbers changed
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PurchaseRequest(Base, TenantScoped, TimestampMixin):
    """A PO the plan needs. Planning only records it; the Purchasing module (not built yet) will turn it
    into a real purchase order: pick the supplier, confirm price and delivery, and send it.

    Purchasing will need: material, quantity + unit, needed-by date, express or normal, which plan and
    orders need it, who asked and when, and a status it moves through
    (requested -> ordered -> received / cancelled). Its arrival date and price then flow back into
    planning through `material_stock.next_arrival_*` and `materials.price_per_unit_paise`.
    """

    __tablename__ = "purchase_requests"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"), index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16))
    needed_by: Mapped[date]
    express: Mapped[bool] = mapped_column(Boolean, default=False)
    order_numbers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(16))  # raise_now | approval
    status: Mapped[str] = mapped_column(String(16), default="requested")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

"""Executive Dashboard: a read-only summary of the other modules (it stores nothing of its own)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Source = Literal["planning", "orders", "purchasing", "billing", "production"]


class Range(BaseModel):
    start: date
    end: date
    days: list[date]
    today: date


class Kpi(BaseModel):
    value: float | None
    unit: str
    note: str
    trend: list[float] = []  # daily values over the range, when there is a real series


class DelayedOrder(BaseModel):
    id: uuid.UUID
    number: str
    customer: str
    due: date
    reason: str


class Kpis(BaseModel):
    utilization: Kpi
    in_progress: Kpi
    cycle_time: Kpi
    delayed: Kpi
    delayed_orders: list[DelayedOrder]


class TimelineRow(BaseModel):
    order_id: uuid.UUID
    number: str
    customer: str
    status: str  # the order's status in Orders
    start: date
    finish: date
    due: date | None
    progress_pct: int | None
    late: bool  # finishes after its due date, or the due date has passed


class PlanRef(BaseModel):
    id: uuid.UUID
    number: str
    approved_at: datetime | None = None
    needs_reapproval: bool = False
    status: str | None = None
    orders: list[str] = []  # order numbers in the working plan (the "new orders")


class MachineOrder(BaseModel):
    number: str
    customer: str
    hours: float  # in the selected range
    added: bool  # from the working plan (not approved yet)


class MachineDay(BaseModel):
    day: date
    current: int | None
    after: int | None


class MachineLoad(BaseModel):
    machine: str
    name: str
    current: int | None  # average % over the working days of the range
    after: int | None
    peak_after: int | None
    peak_day: date | None
    over: bool  # a day goes over 100% after the new orders
    days: list[MachineDay]
    orders: list[MachineOrder]


class Timeline(BaseModel):
    source: Literal["approved", "committed"] | None
    plan: PlanRef | None
    draft: PlanRef | None
    rows: list[TimelineRow]
    machines: list[MachineLoad]


class CashMonth(BaseModel):
    month: str  # 2026-06
    label: str  # Jun
    invoiced: int
    collected: int
    payables: int
    paid: int  # supplier money that actually left the bank


class TopCustomer(BaseModel):
    id: uuid.UUID
    name: str
    sales_paise: int


class CustomerHealth(BaseModel):
    period_label: str
    high_value: int
    repeat: int
    inactive: int
    top: TopCustomer | None
    total_orders: int


class Alert(BaseModel):
    id: str
    source: Source
    tone: Literal["hi", "md", "bl", "ok"]
    title: str
    text: str
    at: date | None  # when it happened / is due
    link: str  # the source record


class DashboardOut(BaseModel):
    range: Range
    kpis: Kpis
    timeline: Timeline
    cash_flow: list[CashMonth]
    customers: CustomerHealth
    alerts: list[Alert]

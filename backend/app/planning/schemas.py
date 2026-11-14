"""API shapes. The plan result mirrors `engine.compute()` so the frontend gets generated types."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# ---- plan result (what every tab reads) -----------------------------------------------------


class OrderInfo(BaseModel):
    number: str
    customer: str
    product: str
    qty: float
    unit: str
    value: int
    deadline: date
    priority: str
    est_margin: float


class RunningRow(BaseModel):
    id: str
    number: str
    customer: str
    product: str
    progress: int
    start: date
    finish: date
    machines: list[str]


class OptionRow(BaseModel):
    start: date
    finish: date
    late_days: int


class SelectionOption(BaseModel):
    orders: list[str]
    value: int
    start: date | None
    end: date | None
    days: int
    alongside: int
    idle_days: int
    idle_machines: list[str]
    utilisation: int
    bottlenecks: int
    bottleneck_names: list[str]
    late: list[str]
    contribution: int
    margin: float
    per_day: int
    rows: dict[str, OptionRow]


class Options(BaseModel):
    own: SelectionOption | None
    part: SelectionOption | None
    full: SelectionOption | None


class Selection(BaseModel):
    orders: dict[str, OrderInfo]
    selected: list[str]
    running: list[RunningRow]
    options: Options


class SeqRow(BaseModel):
    id: str
    rank: int
    start: date
    finish: date
    deadline: date
    buffer: int
    late_days: int
    group: int
    machines: list[str]
    warn_machines: list[str]
    locked: bool
    pinned: date | None
    status: Literal["on_time", "late", "material"]


class Group(BaseModel):
    orders: list[str]
    shared: list[str]


class Hint(BaseModel):
    sequence: list[str]
    title: str
    text: str
    moved: str


class Overview(BaseModel):
    orders: int
    start: date | None
    end: date | None
    days: int
    utilisation: int
    on_time: int
    bottlenecks: int
    parallel: int


class Feasibility(BaseModel):
    ok: bool
    lines: list[str]


class Sequence(BaseModel):
    rule: str
    start: date
    rows: list[SeqRow]
    groups: list[Group]
    hint: Hint | None
    overview: Overview
    feasibility: Feasibility


class Bottleneck(BaseModel):
    kind: Literal["machine", "labour", "material", "material_wait", "late"]
    resource: str
    title: str
    text: str
    size: float
    orders: list[str]
    from_: date = Field(alias="from")
    to: date
    machine: str | None = None
    material: str | None = None
    was: str | None = None


class GanttStep(BaseModel):
    machine: str
    name: str
    start: date
    finish: date
    hours: dict[str, float]
    setup: float


class GanttRow(BaseModel):
    id: str
    running: bool
    steps: list[GanttStep]
    start: date
    finish: date
    deadline: date | None
    over_days: list[date]
    short: bool


class LoadRow(BaseModel):
    machine: str
    name: str
    days: dict[str, int | None]
    over: bool


class Schedule(BaseModel):
    days: list[date]
    today: date
    rows: list[GanttRow]
    load: list[LoadRow]
    bottlenecks: list[Bottleneck]


class FinRow(BaseModel):
    id: str
    value: int
    cost: int
    penalty: int
    fix_cost: int
    contribution: int
    margin: float


class Breakdown(BaseModel):
    materials: int
    labour: int
    machine: int
    overheads: int
    packaging: int


class FixCost(BaseModel):
    id: str
    label: str
    cost: int


class Finance(BaseModel):
    rows: list[FinRow]
    value: int
    cost: int
    mfg_cost: int
    breakdown: Breakdown
    base_contribution: int
    penalty: int
    fix_cost: int
    contribution: int
    margin: float
    per_day: int
    fixes: list[FixCost]


class Fix(BaseModel):
    id: str
    label: str
    cost: int
    penalty_avoided: int
    solves: list[str]
    selected: bool


class Finances(BaseModel):
    before: Finance
    with_: Finance = Field(alias="with")
    fixes: list[Fix]


class Check(BaseModel):
    ok: bool
    title: str
    text: str
    action: str | None = None
    setting: str | None = None


class Approval(BaseModel):
    checks: list[Check]
    ready: int
    total: int


class PurchaseNeed(BaseModel):
    material: str
    code: str
    name: str
    unit: str
    qty: float
    needed_by: date
    orders: list[str]
    express: bool
    kind: str
    requested: bool


class PlanResult(BaseModel):
    selection: Selection
    sequence: Sequence
    schedule: Schedule
    finance: Finances
    approval: Approval
    purchase_needs: list[PurchaseNeed]
    blocked: dict[str, str]


class LastChange(BaseModel):
    summary: str
    tabs: list[int]
    at: datetime


class PlanOut(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    needs_reapproval: bool
    rule: str
    start_date: date
    version: int
    generated_at: datetime | None
    approved_at: datetime | None
    approval_note: str | None
    result: PlanResult
    last_change: LastChange | None


class Diff(BaseModel):
    worse: list[Bottleneck]
    better: list[Bottleneck]
    deliveries: list[dict[str, int | str | date]]
    warn: bool
    blocked: str | None = None


class PreviewOut(BaseModel):
    plan: PlanOut
    diff: Diff
    tabs: list[int]


class PlanPatch(BaseModel):
    """One edit. Every field is optional; the server recalculates everything after any change."""

    selected: list[str] | None = None
    use_option: Literal["part", "full"] | None = None
    rule: Literal["deadline", "value", "margin", "priority", "custom"] | None = None
    start_date: date | None = None
    sequence: list[str] | None = None
    lock: dict[str, bool] | None = None
    pin: dict[str, date | None] | None = None
    fixes: list[str] | None = None
    apply_hint: bool = False


class ApproveIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    raise_open_pos: bool = False


class RaisePoIn(BaseModel):
    material_id: str


class HistoryItem(BaseModel):
    kind: str
    summary: str
    tabs: list[int]
    at: datetime


class PurchaseRequestOut(BaseModel):
    id: uuid.UUID
    material: str
    quantity: Decimal
    unit: str
    needed_by: date
    express: bool
    order_numbers: list[str]
    source: str
    status: str
    created_at: datetime


# ---- company rules (the small ⚙ dialogs next to discretionary numbers) -----------------------


class PlanningRules(BaseModel):
    penalty_mode: Literal["fixed", "percent"] = "fixed"
    penalty_fixed_paise: int = Field(default=20_000_00, ge=0)  # per late day
    penalty_percent: float = Field(default=0.5, ge=0, le=100)  # % of order value per late day
    overhead_pct: float = Field(default=7.0, ge=0, le=100)
    packaging_paise_per_unit: int = Field(default=5, ge=0)
    min_margin_pct: float = Field(default=18.0, ge=0, le=100)


# ---- factory setup --------------------------------------------------------------------------


class DepartmentIn(BaseModel):
    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    hours_per_day: Decimal = Field(ge=0)
    cost_per_hour_paise: int = Field(ge=0)


class MachineIn(BaseModel):
    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    department: str  # department name
    hours_per_shift: Decimal = Field(gt=0, le=24)
    shifts_per_day: int = Field(ge=0, le=3)
    operators: int = Field(ge=0, le=50)
    cost_per_hour_paise: int = Field(ge=0)
    night_shift_cost_per_hour_paise: int = Field(ge=0)


class StepIn(BaseModel):
    machine: str  # machine name
    setup_hours: Decimal = Field(ge=0)
    minutes_per_unit: Decimal = Field(ge=0)


class RouteIn(BaseModel):
    product_id: uuid.UUID
    product: str = ""
    steps: list[StepIn]


class MaterialCostIn(BaseModel):
    id: uuid.UUID
    code: str = ""
    name: str = ""
    unit: str = ""
    price_per_unit_paise: int = Field(ge=0)
    express_cost_paise: int = Field(ge=0)
    express_days: int = Field(ge=0, le=60)
    express_supplier: str | None = None


class DowntimeIn(BaseModel):
    machine: str | None = None  # machine name; None = whole factory closed
    day: date
    hours: Decimal | None = Field(default=None, ge=0)  # None = whole day
    reason: str | None = None


class Factory(BaseModel):
    departments: list[DepartmentIn]
    machines: list[MachineIn]
    routes: list[RouteIn]
    materials: list[MaterialCostIn]
    downtime: list[DowntimeIn]

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["high", "medium", "low"]
Status = Literal["new", "accepted", "planned", "in_production", "completed", "shipped", "cancelled"]
Tone = Literal["hi", "md", "lo", "ok", "bl"]
SortField = Literal[
    "number", "customer", "product", "quantity", "sales", "profit", "margin",
    "processing_days", "ship_date", "priority", "status", "created",
]  # fmt: skip


class Action(BaseModel):
    label: str
    href: str


class Signal(BaseModel):
    """The one-line status shown on cards and the Status column. Worked out in code."""

    kind: Literal["behind", "material_short", "waiting", "ready", "planned", "in_production",
                  "done", "cancelled"]  # fmt: skip
    tone: Tone
    text: str  # card line, e.g. "Steel wire rod short · 2.4 t"
    label: str  # table status, e.g. "Material short"
    action: Action | None = None


class MaterialNeed(BaseModel):
    code: str
    name: str
    unit: str
    required: Decimal
    shortage: Decimal


class OrderPlanRef(BaseModel):
    """The plan an order is in (filled by Planning)."""

    id: uuid.UUID
    number: str
    stage: str  # draft | awaiting | approved | needs_reapproval | completed


class OrderOut(BaseModel):
    id: uuid.UUID
    number: str
    customer_id: uuid.UUID
    customer_name: str
    customer_phone: str | None
    customer_email: str | None
    product_id: uuid.UUID
    product_name: str
    sku: str
    quantity: Decimal
    unit: str
    unit_price_paise: int
    unit_cost_paise: int
    sales_paise: int
    cost_paise: int
    profit_paise: int
    margin_pct: float | None
    processing_days: int
    ship_date: date
    created_at: datetime
    priority: Priority
    status: Status
    progress_pct: int | None
    marked_for_planning: bool
    plan: OrderPlanRef | None = None  # the plan it is in (draft, approved...)
    promised_date: date | None
    cancel_reason: str | None
    notes: str | None
    materials: list[MaterialNeed]
    materials_summary: str | None  # "inventory used" column
    signal: Signal
    rank_score: float | None = None


class OrderPage(BaseModel):
    items: list[OrderOut]
    total: int
    limit: int
    offset: int


class OrderKpis(BaseModel):
    open_orders: int
    high_priority: int
    in_production: int
    ship_in_7_days: int


class OrderCreate(BaseModel):
    customer_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_price_paise: int = Field(ge=0)
    unit_cost_paise: int | None = Field(default=None, ge=0)
    processing_days: int | None = Field(default=None, ge=1, le=365)
    ship_date: date
    priority: Priority = "medium"
    status: Literal["new", "accepted"] = "new"
    notes: str | None = Field(default=None, max_length=2000)


class OrderUpdate(BaseModel):
    customer_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unit_price_paise: int | None = Field(default=None, ge=0)
    unit_cost_paise: int | None = Field(default=None, ge=0)
    processing_days: int | None = Field(default=None, ge=1, le=365)
    ship_date: date | None = None
    priority: Priority | None = None
    status: Status | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    marked_for_planning: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class OrderCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PlanningSelection(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    marked: bool


class PlanningSelectionOut(BaseModel):
    updated: int
    plan: OrderPlanRef | None = None  # the draft the orders are now in
    created: bool = False  # the draft was started for them


RankingMode = Literal["weighted", "requirement", "customer", "profit", "deadline", "priority"]


class RankingWeights(BaseModel):
    requirement: int = Field(default=10, ge=0, le=100)
    customer: int = Field(default=20, ge=0, le=100)
    profit: int = Field(default=25, ge=0, le=100)
    deadline: int = Field(default=30, ge=0, le=100)
    priority: int = Field(default=15, ge=0, le=100)


class RankingSettings(BaseModel):
    mode: RankingMode = "weighted"
    weights: RankingWeights = RankingWeights()

    @field_validator("weights")
    @classmethod
    def _some_weight(cls, w: RankingWeights) -> RankingWeights:
        if sum(w.model_dump().values()) == 0:
            raise ValueError("At least one weight must be above zero.")
        return w

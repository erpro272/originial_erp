import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["critical_short", "low_stock", "in_transit", "adequate"]


class Shortfall(BaseModel):
    """The first order that free stock + deliveries arriving in time can't cover."""

    order_id: uuid.UUID
    number: str
    customer: str
    needed_by: date
    short: Decimal  # how much is missing for it


class Incoming(BaseModel):
    po_id: uuid.UUID
    po_number: str
    status: str  # awaiting_approval | ordered | confirmed
    supplier: str
    quantity: Decimal  # still to come
    expected_date: date
    confirmed: bool


class MaterialRow(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    unit: str
    category: str | None
    grade: str | None
    in_stock: Decimal
    reserved: Decimal  # needed by orders of approved plans, not issued yet
    free: Decimal  # in stock - reserved
    on_order: Decimal  # ordered / confirmed POs still to come
    awaiting_approval: Decimal  # raised, not approved yet (not counted as on order)
    reorder_level: Decimal
    price_per_unit_paise: int
    stock_value_paise: int
    status: Status
    reason: str  # why it has this status, one line
    shortfall: Shortfall | None = None
    next_need: str | None = None  # "Needed for ORD-1036 (Hero MotoCorp)"
    incoming: list[Incoming] = []
    suggested_qty: Decimal  # what a PO raised now should cover
    supplier: str | None = None  # the usual supplier


class Kpis(BaseModel):
    skus: int
    below_reorder: int
    on_order: int  # open POs (ordered / confirmed)
    awaiting_approval: int
    stock_value_paise: int


class PoLine(BaseModel):
    id: uuid.UUID
    material_id: uuid.UUID
    material: str
    code: str
    quantity: Decimal
    unit: str
    price_per_unit_paise: int
    received_qty: Decimal


class PoOut(BaseModel):
    id: uuid.UUID
    number: str
    supplier: str
    status: str
    expected_date: date
    confirmed: bool
    note: str | None
    source: str
    created_at: datetime
    approved_at: datetime | None
    cancel_reason: str | None
    value_paise: int
    lines: list[PoLine]


class InventoryOut(BaseModel):
    kpis: Kpis
    materials: list[MaterialRow]
    attention: list[MaterialRow]  # critical short, then low stock, then in transit
    purchase_orders: list[PoOut]  # open ones, newest first
    categories: list[str]
    suppliers: list[str]
    today: date


class PoRaiseIn(BaseModel):
    material_id: uuid.UUID
    supplier: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    price_per_unit_paise: int = Field(ge=0)
    expected_date: date
    note: str | None = Field(default=None, max_length=2000)


class ConfirmIn(BaseModel):
    expected_date: date  # the supplier's date


class ReceiveIn(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=2000)


class CancelPoIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

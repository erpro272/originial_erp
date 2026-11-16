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


class Need(BaseModel):
    """An order that needs this material (for linking a PO to it)."""

    number: str
    customer: str
    needed_by: date
    qty: Decimal


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
    needs: list[Need] = []  # orders that need it, in order of need


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
    received_qty: Decimal  # QC accepted, in stock
    rejected_qty: Decimal = Decimal("0")  # QC rejected (supplier owes it again)


Stage = Literal["pending_approval", "sent", "confirmed", "in_transit", "delayed", "arriving_today", "at_gate",
                "received", "cancelled"]  # fmt: skip


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
    # what the screens show (worked out from status + dates)
    stage: Stage = "pending_approval"
    stage_text: str = ""  # "1 day behind schedule", "Gate entry logged · ready for QC"
    priority: Literal["high", "medium", "low"] = "medium"  # the linked orders' highest, else the PO's own
    orders: list[str] = []  # linked order numbers
    needed_by: date | None = None  # earliest date a linked order needs the material
    open_value_paise: int = 0  # value still to come
    dispatched_at: datetime | None = None
    gate_qty: Decimal | None = None
    gate_ref: str | None = None
    gate_at: datetime | None = None


class PoEventOut(BaseModel):
    kind: str
    summary: str
    at: datetime
    by: str | None = None


class PoDetail(PoOut):
    events: list[PoEventOut] = []


class PurchaseKpis(BaseModel):
    open: int
    pending_approval: int
    in_transit: int  # dispatched or at the gate
    open_spend_paise: int  # value of what is still to come on open POs


class PurchasesOut(BaseModel):
    kpis: PurchaseKpis
    attention: list[PoOut]  # action required (pending approval), delayed, arriving today / at the gate
    purchase_orders: list[PoOut]  # every PO, newest first
    suppliers: list[str]
    today: date


class InventoryOut(BaseModel):
    kpis: Kpis
    materials: list[MaterialRow]
    attention: list[MaterialRow]  # critical short, then low stock, then in transit
    purchase_orders: list[PoOut]  # open ones, newest first
    categories: list[str]
    suppliers: list[str]
    today: date


Priority = Literal["high", "medium", "low"]


class PoRaiseIn(BaseModel):
    material_id: uuid.UUID
    supplier: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    price_per_unit_paise: int = Field(ge=0)
    expected_date: date
    note: str | None = Field(default=None, max_length=2000)
    order_numbers: list[str] = Field(default=[], max_length=50)  # orders it is for (optional)
    priority: Priority | None = None  # used when no order is linked


class PoEditIn(BaseModel):
    """Change a PO while it waits for approval."""

    supplier: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0)
    price_per_unit_paise: int | None = Field(default=None, ge=0)
    expected_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    order_numbers: list[str] | None = Field(default=None, max_length=50)
    priority: Priority | None = None


class DispatchIn(BaseModel):
    expected_date: date | None = None  # the supplier's arrival date, if it changed
    note: str | None = Field(default=None, max_length=2000)


class GateEntryIn(BaseModel):
    quantity: Decimal = Field(gt=0)
    reference: str = Field(min_length=1, max_length=100)  # challan / vehicle no.
    note: str | None = Field(default=None, max_length=2000)


class QcIn(BaseModel):
    accepted: Decimal = Field(ge=0)
    rejected: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str | None = Field(default=None, max_length=2000)  # required when something is rejected


class FollowUpIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    promised_date: date | None = None  # the supplier's new date


class ConfirmIn(BaseModel):
    expected_date: date  # the supplier's date


class CancelPoIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

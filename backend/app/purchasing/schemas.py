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
    preferred: bool = False  # `supplier` is the one chosen in Supplier comparison
    preferred_rate_paise: int | None = None  # its rate (valid quote, else last price paid)


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


# ---- supplier comparison ------------------------------------------------------------------------


class ScoringRules(BaseModel):
    """How "Best overall" weighs the supplier measures (company setting `supplier-scoring`), and when a
    supplier gets a risk flag."""

    price_weight: float = Field(default=40, ge=0, le=100)
    on_time_weight: float = Field(default=25, ge=0, le=100)
    quality_weight: float = Field(default=25, ge=0, le=100)
    lead_weight: float = Field(default=10, ge=0, le=100)
    late_risk_below: float = Field(default=90, ge=0, le=100)  # on-time %
    quality_risk_above: float = Field(default=1.0, ge=0, le=100)  # defect %


class SupplierRow(BaseModel):
    """One supplier for one material."""

    supplier_id: uuid.UUID
    supplier: str
    material_id: uuid.UUID
    material: str
    code: str
    category: str | None
    unit: str
    rate_paise: int | None  # per unit
    rate_source: Literal["quote", "last_po", "none"]
    lead_days: float | None
    lead_source: Literal["actual", "quote", "none"]
    on_time_pct: float | None  # supplier-wide, deliveries at the gate by the committed date
    defect_pct: float | None  # supplier-wide, QC rejected / inspected
    quality_score: float | None  # out of 10
    deliveries: int  # supplier-wide, last 12 months
    active_pos: int  # supplier-wide, open POs
    overall: float | None  # %
    stars: int  # 0-5
    flags: list[str]
    note: str
    preferred: bool  # the chosen supplier for this material
    active: bool  # an open PO, a PO in the last 6 months or a quote in the last 90 days
    quote_valid_until: date | None = None


class TopCard(BaseModel):
    badges: list[
        Literal["Best overall", "Highest quality", "Lowest cost"]
    ]  # each badge goes to its real winner
    pct: float
    row: SupplierRow


class MaterialRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    unit: str
    needed: bool  # an order needs it now


class QuoteOut(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier: str
    material_id: uuid.UUID
    material: str
    code: str
    unit: str
    status: Literal["requested", "received"]
    quantity: Decimal | None
    rate_paise: int | None
    lead_days: int | None
    valid_until: date | None
    note: str | None
    created_at: datetime
    replied_at: datetime | None


class ComparisonKpis(BaseModel):
    active_suppliers: int
    avg_on_time_pct: float | None
    avg_lead_days: float | None
    saved_30d_paise: int  # POs approved in the last 30 days vs the material's average rate (90 days)


class ComparisonOut(BaseModel):
    kpis: ComparisonKpis
    materials: list[MaterialRef]
    default_material_id: uuid.UUID | None  # the one most needed now
    top: dict[str, list[TopCard]]  # material id -> recommended suppliers
    rows: list[SupplierRow]
    quotes: list[QuoteOut]  # waiting for a reply, and replies from the last 90 days
    rules: ScoringRules
    today: date


class DeliveryOut(BaseModel):
    po_number: str
    material: str
    unit: str
    promised_date: date | None
    arrived: date
    on_time: bool | None
    lead_days: int | None
    accepted: Decimal | None
    rejected: Decimal | None


class SupplierDetail(BaseModel):
    id: uuid.UUID
    name: str
    deliveries: list[DeliveryOut]
    quotes: list[QuoteOut]
    open_pos: list[str]


class QuoteRequestIn(BaseModel):
    material_id: uuid.UUID
    suppliers: list[str] = Field(min_length=1, max_length=10)
    quantity: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=2000)


class QuoteReplyIn(BaseModel):
    rate_paise: int = Field(gt=0)
    lead_days: int = Field(ge=0, le=365)
    valid_until: date
    note: str | None = Field(default=None, max_length=2000)


class PreferredIn(BaseModel):
    material_id: uuid.UUID
    supplier_id: uuid.UUID

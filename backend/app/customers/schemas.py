import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Health = Literal["new", "repeat", "high_value", "declining", "inactive", "dormant"]
Tier = Literal["key", "standard", "occasional"]
PeriodPreset = Literal["this_month", "this_quarter", "fytd", "last_12_months", "custom"]
FollowupKind = Literal["call", "whatsapp", "email", "note", "reminder"]
CustomerSort = Literal[
    "name", "total_sales", "invoices", "aov", "units", "outstanding", "last_purchase",
    "frequency", "health", "state", "created",
]  # fmt: skip


class AddressIn(BaseModel):
    kind: Literal["billing", "shipping"]
    line1: str = Field(min_length=1, max_length=300)
    line2: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    pincode: str | None = Field(default=None, pattern=r"^\d{6}$")


class AddressOut(AddressIn):
    id: uuid.UUID


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    designation: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    is_primary: bool = False


class ContactOut(ContactIn):
    id: uuid.UUID
    email: str | None = None


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    gstin: str | None = Field(default=None, max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit_paise: int | None = Field(default=None, ge=0)
    tier: Tier = "standard"
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_ifsc: str | None = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank_account: str | None = Field(default=None, pattern=r"^\d{6,18}$")
    upi_id: str | None = Field(default=None, pattern=r"^[\w.\-]{2,}@[a-zA-Z]{2,}$")
    addresses: list[AddressIn] = Field(default_factory=list, max_length=10)
    contacts: list[ContactIn] = Field(default_factory=list, max_length=20)

    @field_validator("gstin", "pan")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if v else None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return sorted({t.strip()[:40] for t in v if t.strip()})


class CustomerPatch(BaseModel):
    """Partial update; same rules as CustomerIn. Lists replace the existing ones when sent."""

    name: str | None = Field(default=None, min_length=2, max_length=200)
    gstin: str | None = Field(default=None, max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit_paise: int | None = Field(default=None, ge=0)
    tier: Tier | None = None
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_ifsc: str | None = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank_account: str | None = Field(default=None, pattern=r"^\d{6,18}$")
    upi_id: str | None = Field(default=None, pattern=r"^[\w.\-]{2,}@[a-zA-Z]{2,}$")
    addresses: list[AddressIn] | None = None
    contacts: list[ContactIn] | None = None
    is_active: bool | None = None

    @field_validator("gstin", "pan")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if v else None


class CustomerRow(BaseModel):
    """One row of the customers table: master data + period metrics + health."""

    id: uuid.UUID
    name: str
    gstin: str | None
    pan: str | None
    state_code: str | None
    state: str | None
    city: str | None
    phone: str | None
    email: str | None
    tier: Tier
    tags: list[str]
    payment_terms_days: int | None
    credit_limit_paise: int | None
    source: str
    created_at: datetime
    primary_contact: str | None
    # period metrics
    total_sales_paise: int
    invoices: int
    aov_paise: int | None
    units_sold: Decimal
    previous_sales_paise: int
    sales_change_pct: float | None
    # all-time
    outstanding_paise: int
    last_purchase: date | None
    days_since_last: int | None
    first_purchase: date | None
    frequency_days: float | None
    lifetime_sales_paise: int
    lifetime_invoices: int
    credit_used_pct: float | None
    open_followups: int
    next_followup: date | None
    health: Health | None
    health_tags: list[Health]


class Period(BaseModel):
    preset: PeriodPreset
    date_from: date
    date_to: date
    prev_from: date
    prev_to: date


class Overview(BaseModel):
    total_customers: int
    active_customers: int
    active_pct: float
    new_customers: int
    units_sold: Decimal


class CustomerPage(BaseModel):
    items: list[CustomerRow]
    total: int
    limit: int
    offset: int
    period: Period
    overview: Overview
    health_counts: dict[str, int]
    available_fields: int


class HealthSettings(BaseModel):
    repeat_min_invoices: int = Field(default=2, ge=2, le=50)
    repeat_recent_days: int = Field(default=60, ge=1, le=365)
    inactive_days: int = Field(default=60, ge=1, le=730)
    dormant_days: int = Field(default=90, ge=2, le=1000)
    high_value_top_pct: int = Field(default=10, ge=1, le=50)
    declining_drop_pct: int = Field(default=30, ge=1, le=100)


class FollowupIn(BaseModel):
    kind: FollowupKind
    note: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None
    assigned_to: uuid.UUID | None = None


class FollowupOut(BaseModel):
    id: uuid.UUID
    kind: FollowupKind
    note: str | None
    due_date: date | None
    done_at: datetime | None
    created_at: datetime
    created_by_name: str | None


class InvoiceBrief(BaseModel):
    id: uuid.UUID
    invoice_number: str | None
    invoice_date: date | None
    grand_total_paise: int | None
    balance_due_paise: int | None
    status: str  # paid | partial | unpaid
    source: str
    upload_id: uuid.UUID | None


class MonthPoint(BaseModel):
    month: date
    sales_paise: int


class ProductBought(BaseModel):
    name: str
    uom: str | None
    quantity: Decimal
    value_paise: int


class CustomerDetail(BaseModel):
    row: CustomerRow
    addresses: list[AddressOut]
    contacts: list[ContactOut]
    notes: str | None
    bank_name: str | None
    bank_ifsc: str | None
    bank_account: str | None  # masked unless the role may see it
    upi_id: str | None
    sensitive_visible: bool
    followups: list[FollowupOut]
    invoices: list[InvoiceBrief]
    monthly_sales: list[MonthPoint]
    top_products: list[ProductBought]
    merged_into_id: uuid.UUID | None


class MergeIn(BaseModel):
    source_id: uuid.UUID = Field(description="Duplicate customer to merge away")

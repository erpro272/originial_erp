import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core import clock
from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission
from app.customers import service
from app.customers.schemas import (
    CustomerDetail,
    CustomerIn,
    CustomerPage,
    CustomerPatch,
    CustomerSort,
    FollowupIn,
    FollowupOut,
    HealthSettings,
    MergeIn,
    PeriodPreset,
)

router = APIRouter(prefix="/customers", tags=["customers"])
Reader = Annotated[Principal, Depends(require(Permission.CUSTOMERS_READ))]
Writer = Annotated[Principal, Depends(require(Permission.CUSTOMERS_WRITE))]


class CustomerOption(BaseModel):
    id: uuid.UUID
    name: str
    gstin: str | None
    tier: str


class Created(BaseModel):
    id: uuid.UUID


@router.get("")
async def list_customers(
    db: TenantDB,
    _: Reader,
    period: PeriodPreset = "fytd",
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    health: Annotated[list[str] | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
    product: str | None = None,
    outstanding_only: bool = False,
    min_sales_paise: int | None = None,
    max_sales_paise: int | None = None,
    followups_due: bool = False,
    sort: CustomerSort = "total_sales",
    desc: bool = True,
    limit: Annotated[int, Query(ge=1, le=1000)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerPage:
    p = service.resolve_period(period, date_from, date_to, clock.today())
    f = service.CustomerFilters(
        q=q, health=health or [], state_codes=state or [], tiers=tier or [], product=product,
        outstanding_only=outstanding_only, min_sales_paise=min_sales_paise,
        max_sales_paise=max_sales_paise, followups_due=followups_due,
    )  # fmt: skip
    return await service.list_customers(db, p, f, sort, desc, limit, offset)


@router.get("/options")
async def options(db: TenantDB, _: Reader) -> list[CustomerOption]:
    """Lightweight list for pickers (filters, order form)."""
    rows = sorted(await service.active_customers(db), key=lambda c: c.name.lower())
    return [CustomerOption(id=c.id, name=c.name, gstin=c.gstin, tier=c.tier) for c in rows]


@router.get("/health-settings")
async def get_health(db: TenantDB, _: Reader) -> HealthSettings:
    return await service.get_health_settings(db)


@router.put("/health-settings")
async def put_health(
    body: HealthSettings, db: TenantDB, p: Annotated[Principal, Depends(require(Permission.SETTINGS_WRITE))]
) -> HealthSettings:
    return await service.put_health_settings(db, p.user_id, body)


@router.get("/{customer_id}")
async def detail(
    customer_id: uuid.UUID,
    db: TenantDB,
    p: Reader,
    period: PeriodPreset = "fytd",
    date_from: date | None = None,
    date_to: date | None = None,
) -> CustomerDetail:
    per = service.resolve_period(period, date_from, date_to, clock.today())
    return await service.get_detail(db, customer_id, per, p.can(Permission.SENSITIVE_VIEW))


@router.post("", status_code=201)
async def create(body: CustomerIn, db: TenantDB, p: Writer) -> Created:
    return Created(id=(await service.create_customer(db, p.user_id, body)).id)


@router.patch("/{customer_id}")
async def update(customer_id: uuid.UUID, body: CustomerPatch, db: TenantDB, p: Writer) -> Created:
    return Created(id=(await service.update_customer(db, p.user_id, customer_id, body)).id)


@router.post("/{customer_id}/merge")
async def merge(customer_id: uuid.UUID, body: MergeIn, db: TenantDB, p: Writer) -> Created:
    """Merge `source_id` (a duplicate) into this customer."""
    return Created(id=(await service.merge(db, p.user_id, customer_id, body.source_id)).id)


@router.post("/{customer_id}/followups", status_code=201)
async def add_followup(customer_id: uuid.UUID, body: FollowupIn, db: TenantDB, p: Reader) -> FollowupOut:
    return await service.add_followup(db, p.user_id, customer_id, body)


@router.post("/{customer_id}/followups/{followup_id}/done", status_code=204)
async def done_followup(customer_id: uuid.UUID, followup_id: uuid.UUID, db: TenantDB, p: Reader) -> None:
    await service.complete_followup(db, p.user_id, customer_id, followup_id)

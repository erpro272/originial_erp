import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.core import clock
from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission
from app.orders import service
from app.orders.schemas import (
    OrderCancel,
    OrderCreate,
    OrderKpis,
    OrderOut,
    OrderPage,
    OrderUpdate,
    PlanningSelection,
    RankingSettings,
    SortField,
)

router = APIRouter(prefix="/orders", tags=["orders"])
Reader = Annotated[Principal, Depends(require(Permission.ORDERS_READ))]
Writer = Annotated[Principal, Depends(require(Permission.ORDERS_WRITE))]


@router.get("")
async def list_orders(
    db: TenantDB,
    _: Reader,
    scope: Literal["current", "past", "all"] = "current",
    customer_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    priority: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    max_processing_days: Annotated[int | None, Query(ge=1)] = None,
    ship_from: date | None = None,
    ship_to: date | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    planning_only: bool = False,
    sort: SortField = "ship_date",
    desc: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    f = service.OrderFilters(
        scope=scope, customer_ids=customer_id or [], priorities=priority or [],
        statuses=status or [], q=q, max_processing_days=max_processing_days,
        ship_from=ship_from, ship_to=ship_to, created_from=created_from, created_to=created_to,
        planning_only=planning_only,
    )  # fmt: skip
    items, total = await service.list_orders(db, f, sort, desc, limit, offset)
    return OrderPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/kpis")
async def kpis(db: TenantDB, _: Reader) -> OrderKpis:
    return await service.kpis(db)


@router.get("/top")
async def top(db: TenantDB, _: Reader, n: Annotated[int, Query(ge=1, le=10)] = 3) -> list[OrderOut]:
    """Top-N "needs attention" orders, ranked by the owner's ranking settings."""
    return await service.top_orders(db, n)


@router.get("/ranking-settings")
async def get_ranking(db: TenantDB, _: Reader) -> RankingSettings:
    return await service.get_ranking(db)


@router.put("/ranking-settings")
async def put_ranking(
    body: RankingSettings,
    db: TenantDB,
    p: Annotated[Principal, Depends(require(Permission.SETTINGS_WRITE))],
) -> RankingSettings:
    return await service.put_ranking(db, p.user_id, body)


@router.post("/planning-selection")
async def planning_selection(body: PlanningSelection, db: TenantDB, p: Writer) -> dict[str, int]:
    return {"updated": await service.set_planning_selection(db, p.user_id, body.order_ids, body.marked)}


@router.get("/today")
async def today(_: Reader) -> dict[str, date]:
    """Server's business date (all "ships in N days" maths uses it)."""
    return {"today": clock.today()}


@router.get("/{order_id}")
async def get_order(order_id: uuid.UUID, db: TenantDB, _: Reader) -> OrderOut:
    return await service.get_order(db, order_id)


@router.post("", status_code=201)
async def create(body: OrderCreate, db: TenantDB, p: Writer) -> OrderOut:
    return await service.create_order(db, p.user_id, body)


@router.patch("/{order_id}")
async def update(order_id: uuid.UUID, body: OrderUpdate, db: TenantDB, p: Writer) -> OrderOut:
    return await service.update_order(db, p.user_id, order_id, body)


@router.post("/{order_id}/cancel")
async def cancel(order_id: uuid.UUID, body: OrderCancel, db: TenantDB, p: Writer) -> OrderOut:
    return await service.cancel_order(db, p.user_id, order_id, body)

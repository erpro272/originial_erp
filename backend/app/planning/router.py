import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission
from app.planning import service
from app.planning.schemas import (
    ApproveIn,
    Factory,
    HistoryItem,
    PlanningObjective,
    PlanningRules,
    PlanOut,
    PlanPatch,
    PreviewOut,
    PurchaseRequestOut,
    RaisePoIn,
    SendBackIn,
)

router = APIRouter(prefix="/planning", tags=["planning"])
Reader = Annotated[Principal, Depends(require(Permission.PLANNING_READ))]
Writer = Annotated[Principal, Depends(require(Permission.PLANNING_WRITE))]
Approver = Annotated[Principal, Depends(require(Permission.PLANNING_APPROVE))]
SettingsWriter = Annotated[Principal, Depends(require(Permission.SETTINGS_WRITE))]


@router.get("/plan")
async def current_plan(db: TenantDB, _: Reader) -> PlanOut | None:
    """The working plan (recalculated if anything it depends on changed), or the last approved one."""
    return await service.get_current(db)


@router.post("/plans", status_code=201)
async def create_plan(db: TenantDB, p: Writer) -> PlanOut:
    return await service.create_plan(db, p.user_id)


@router.patch("/plans/{plan_id}")
async def update_plan(
    db: TenantDB, p: Writer, plan_id: uuid.UUID, body: PlanPatch, preview: bool = False
) -> PreviewOut:
    """Any edit. With `preview=true` nothing is saved: returns the recalculated plan and what got worse/better."""
    return await service.update_plan(db, p.user_id, plan_id, body, preview)


@router.post("/plans/{plan_id}/generate")
async def generate(db: TenantDB, p: Writer, plan_id: uuid.UUID) -> PlanOut:
    return await service.generate(db, p.user_id, plan_id)


@router.post("/plans/{plan_id}/save-schedule")
async def save_schedule(db: TenantDB, p: Writer, plan_id: uuid.UUID) -> PlanOut:
    return await service.save_schedule(db, p.user_id, plan_id)


@router.post("/plans/{plan_id}/purchase-requests")
async def raise_po(db: TenantDB, p: Writer, plan_id: uuid.UUID, body: RaisePoIn) -> PlanOut:
    return await service.raise_po(db, p.user_id, plan_id, body.material_id)


@router.post("/plans/{plan_id}/approve")
async def approve(db: TenantDB, p: Approver, plan_id: uuid.UUID, body: ApproveIn) -> PlanOut:
    return await service.approve(db, p.user_id, plan_id, body)


@router.post("/plans/{plan_id}/send-back")
async def send_back(db: TenantDB, p: Approver, plan_id: uuid.UUID, body: SendBackIn) -> PlanOut:
    return await service.send_back(db, p.user_id, plan_id, body.note)


@router.get("/plans/{plan_id}/history")
async def history(db: TenantDB, _: Reader, plan_id: uuid.UUID) -> list[HistoryItem]:
    return await service.history(db, plan_id)


@router.get("/purchase-requests")
async def purchase_requests(db: TenantDB, _: Reader) -> list[PurchaseRequestOut]:
    return await service.purchase_requests(db)


@router.get("/rules")
async def get_rules(db: TenantDB, _: Reader) -> PlanningRules:
    return await service.get_rules(db)


@router.put("/rules")
async def put_rules(db: TenantDB, p: SettingsWriter, body: PlanningRules) -> PlanningRules:
    return await service.put_rules(db, p.user_id, body)


@router.get("/objective")
async def get_objective(db: TenantDB, _: Reader) -> PlanningObjective:
    """How "Best score" ranks the selection options (edited in Factory setup later)."""
    return await service.get_objective(db)


@router.put("/objective")
async def put_objective(db: TenantDB, p: SettingsWriter, body: PlanningObjective) -> PlanningObjective:
    return await service.put_objective(db, p.user_id, body)


@router.get("/factory")
async def get_factory(db: TenantDB, _: Reader) -> Factory:
    return await service.get_factory(db)


@router.put("/factory")
async def put_factory(db: TenantDB, p: SettingsWriter, body: Factory) -> Factory:
    return await service.put_factory(db, p.user_id, body)

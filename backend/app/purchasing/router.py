import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission
from app.purchasing import service
from app.purchasing.schemas import (
    CancelPoIn,
    ConfirmIn,
    DispatchIn,
    FollowUpIn,
    GateEntryIn,
    InventoryOut,
    PoDetail,
    PoEditIn,
    PoOut,
    PoRaiseIn,
    PurchasesOut,
    QcIn,
)

router = APIRouter(prefix="/purchasing", tags=["purchasing"])
Reader = Annotated[Principal, Depends(require(Permission.PURCHASING_READ))]
Writer = Annotated[Principal, Depends(require(Permission.PURCHASING_WRITE))]
Approver = Annotated[Principal, Depends(require(Permission.PURCHASING_APPROVE))]


@router.get("/inventory")
async def inventory(db: TenantDB, _: Reader) -> InventoryOut:
    """Stock, reserved, on order and status per material; needs-attention cards; open POs."""
    return await service.inventory(db)


@router.get("/purchases")
async def purchases(db: TenantDB, _: Reader) -> PurchasesOut:
    """Raw Material Purchase: every PO with its stage, KPIs and the POs that need attention."""
    return await service.purchases(db)


@router.get("/purchase-orders")
async def purchase_orders(db: TenantDB, _: Reader) -> list[PoOut]:
    return await service.list_pos(db)


@router.get("/purchase-orders/{po_id}")
async def get_po(db: TenantDB, _: Reader, po_id: uuid.UUID) -> PoDetail:
    """One PO with its timeline."""
    return await service.get_po(db, po_id)


@router.post("/purchase-orders", status_code=201)
async def raise_po(db: TenantDB, p: Writer, body: PoRaiseIn) -> PoDetail:
    """Raise a PO; it waits for the owner's approval before it counts as on order."""
    return await service.raise_po(db, p.user_id, body)


@router.patch("/purchase-orders/{po_id}")
async def edit_po(db: TenantDB, p: Writer, po_id: uuid.UUID, body: PoEditIn) -> PoDetail:
    """Change a PO while it waits for approval."""
    return await service.edit_po(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/approve")
async def approve(db: TenantDB, p: Approver, po_id: uuid.UUID) -> PoDetail:
    """Owner approves: the PO is sent to the supplier and counts as on order."""
    return await service.approve_po(db, p.user_id, po_id)


@router.post("/purchase-orders/{po_id}/confirm")
async def confirm(db: TenantDB, p: Writer, po_id: uuid.UUID, body: ConfirmIn) -> PoDetail:
    """The supplier confirmed the order and its delivery date."""
    return await service.confirm_po(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/dispatch")
async def dispatch(db: TenantDB, p: Writer, po_id: uuid.UUID, body: DispatchIn) -> PoDetail:
    """The supplier dispatched the goods: in transit."""
    return await service.dispatch_po(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/gate-entry")
async def gate_entry(db: TenantDB, p: Writer, po_id: uuid.UUID, body: GateEntryIn) -> PoDetail:
    """Goods arrived at the gate: waiting for QC (not in stock yet)."""
    return await service.gate_entry(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/qc")
async def qc(db: TenantDB, p: Writer, po_id: uuid.UUID, body: QcIn) -> PoDetail:
    """QC: accepted quantity into stock, rejected quantity back to the supplier."""
    return await service.quality_check(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/follow-up")
async def follow_up(db: TenantDB, p: Writer, po_id: uuid.UUID, body: FollowUpIn) -> PoDetail:
    """Chased the supplier: note and the new promised date."""
    return await service.follow_up(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/cancel")
async def cancel(db: TenantDB, p: Writer, po_id: uuid.UUID, body: CancelPoIn) -> PoDetail:
    return await service.cancel_po(db, p.user_id, po_id, body.reason)

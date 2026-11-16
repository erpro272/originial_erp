import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission
from app.purchasing import service
from app.purchasing.schemas import CancelPoIn, ConfirmIn, InventoryOut, PoOut, RaisePoIn, ReceiveIn

router = APIRouter(prefix="/purchasing", tags=["purchasing"])
Reader = Annotated[Principal, Depends(require(Permission.PURCHASING_READ))]
Writer = Annotated[Principal, Depends(require(Permission.PURCHASING_WRITE))]
Approver = Annotated[Principal, Depends(require(Permission.PURCHASING_APPROVE))]


@router.get("/inventory")
async def inventory(db: TenantDB, _: Reader) -> InventoryOut:
    """Stock, reserved, on order and status per material; needs-attention cards; open POs."""
    return await service.inventory(db)


@router.get("/purchase-orders")
async def purchase_orders(db: TenantDB, _: Reader) -> list[PoOut]:
    return await service.list_pos(db)


@router.post("/purchase-orders", status_code=201)
async def raise_po(db: TenantDB, p: Writer, body: RaisePoIn) -> PoOut:
    """Raise a PO; it waits for the owner's approval before it counts as on order."""
    return await service.raise_po(db, p.user_id, body)


@router.post("/purchase-orders/{po_id}/approve")
async def approve(db: TenantDB, p: Approver, po_id: uuid.UUID) -> PoOut:
    return await service.approve_po(db, p.user_id, po_id)


@router.post("/purchase-orders/{po_id}/confirm")
async def confirm(db: TenantDB, p: Writer, po_id: uuid.UUID, body: ConfirmIn) -> PoOut:
    """The supplier confirmed the order and its delivery date."""
    return await service.confirm_po(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/receive")
async def receive(db: TenantDB, p: Writer, po_id: uuid.UUID, body: ReceiveIn) -> PoOut:
    """Goods received: stock goes up (ledger)."""
    return await service.receive(db, p.user_id, po_id, body)


@router.post("/purchase-orders/{po_id}/cancel")
async def cancel(db: TenantDB, p: Writer, po_id: uuid.UUID, body: CancelPoIn) -> PoOut:
    return await service.cancel_po(db, p.user_id, po_id, body.reason)

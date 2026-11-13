import uuid
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.catalog import service
from app.core.auth import CurrentPrincipal, TenantDB

router = APIRouter(prefix="/catalog", tags=["catalog"])


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sku: str
    name: str
    unit: str
    hsn: str | None
    gst_rate: Decimal
    processing_days: int
    unit_price_paise: int
    unit_cost_paise: int


@router.get("/products")
async def products(db: TenantDB, _: CurrentPrincipal) -> list[ProductOut]:
    return [ProductOut.model_validate(p) for p in await service.list_products(db)]

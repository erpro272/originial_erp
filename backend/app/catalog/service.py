"""Catalog reads used by other modules (no other module touches these tables)."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Material, MaterialStock, Product, ProductMaterial


@dataclass(frozen=True)
class BomLine:
    material_id: uuid.UUID
    code: str
    name: str
    unit: str
    qty_per_unit: Decimal


@dataclass(frozen=True)
class Stock:
    on_hand: Decimal
    next_arrival_date: date | None
    next_arrival_qty: Decimal | None


async def list_products(session: AsyncSession) -> list[Product]:
    return list((await session.execute(select(Product).order_by(Product.name))).scalars())


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> Product | None:
    return await session.get(Product, product_id)


async def boms(session: AsyncSession) -> dict[uuid.UUID, list[BomLine]]:
    rows = await session.execute(
        select(ProductMaterial.product_id, Material, ProductMaterial.qty_per_unit).join(
            Material, Material.id == ProductMaterial.material_id
        )
    )
    out: dict[uuid.UUID, list[BomLine]] = {}
    for pid, m, q in rows:
        out.setdefault(pid, []).append(BomLine(m.id, m.code, m.name, m.unit, q))
    return out


async def stock(session: AsyncSession) -> dict[uuid.UUID, Stock]:
    rows = (await session.execute(select(MaterialStock))).scalars()
    return {r.material_id: Stock(r.on_hand, r.next_arrival_date, r.next_arrival_qty) for r in rows}

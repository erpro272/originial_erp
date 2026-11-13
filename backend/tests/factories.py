"""Small helpers that insert feature data directly (as the app role, inside RLS)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.catalog.models import Material, MaterialStock, Product, ProductMaterial
from app.core.db import tenant_session
from app.core.gst import gstin_checksum
from app.customers.models import Customer
from app.invoices.models import Invoice, InvoiceLine


def gstin(state: str, pan: str) -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_checksum(body)


async def product(tid: uuid.UUID, sku: str, name: str, *, days: int = 3, price: int = 1000, cost: int = 800,
                  bom: list[tuple[str, str, Decimal]] | None = None) -> uuid.UUID:  # fmt: skip
    """bom: (material code, name, qty per unit in tonnes)."""
    async with tenant_session(tid) as s:
        p = Product(sku=sku, name=name, processing_days=days, unit_price_paise=price, unit_cost_paise=cost)
        s.add(p)
        await s.flush()
        for code, mname, q in bom or []:
            from sqlalchemy import select

            m = (await s.execute(select(Material).where(Material.code == code))).scalar_one_or_none()
            if m is None:
                m = Material(code=code, name=mname, unit="t")
                s.add(m)
                await s.flush()
            s.add(ProductMaterial(product_id=p.id, material_id=m.id, qty_per_unit=q))
        return p.id


async def stock(tid: uuid.UUID, code: str, on_hand: Decimal, arrival: date | None = None) -> None:
    from sqlalchemy import select

    async with tenant_session(tid) as s:
        m = (await s.execute(select(Material).where(Material.code == code))).scalar_one()
        s.add(MaterialStock(material_id=m.id, on_hand=on_hand, next_arrival_date=arrival,
                            next_arrival_qty=Decimal(5) if arrival else None))  # fmt: skip


async def customer(tid: uuid.UUID, name: str, *, gst: str | None = None, tier: str = "standard",
                   phone: str | None = None, state: str | None = None) -> uuid.UUID:  # fmt: skip
    async with tenant_session(tid) as s:
        c = Customer(name=name, gstin=gst, tier=tier, phone=phone, state_code=state or (gst[:2] if gst else None),
                     pan=gst[2:12] if gst else None)  # fmt: skip
        s.add(c)
        await s.flush()
        return c.id


async def invoice(tid: uuid.UUID, cid: uuid.UUID, day: date, total_rupees: int, *, qty: int = 100,
                  uom: str = "PCS", balance_rupees: int = 0, product_name: str = "M10 hex bolts",
                  number: str | None = None) -> uuid.UUID:  # fmt: skip
    async with tenant_session(tid) as s:
        inv = Invoice(customer_id=cid, invoice_number=number or f"INV-{uuid.uuid4().hex[:8]}", invoice_date=day,
                      grand_total_paise=total_rupees * 100, balance_due_paise=balance_rupees * 100, source="seed")  # fmt: skip
        s.add(inv)
        await s.flush()
        s.add(InvoiceLine(invoice_id=inv.id, line_no=1, product_name=product_name, quantity=Decimal(qty), uom=uom,
                          total_paise=total_rupees * 100))  # fmt: skip
        return inv.id


def ago(today: date, days: int) -> date:
    return today - timedelta(days=days)

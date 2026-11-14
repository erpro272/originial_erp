"""Planning demo scenario, written as an idempotent upsert.

Run on any demo database (fresh or old) without dropping anything:

    python -m seed.planning_demo            # all companies that have the demo orders

What it sets (matched by natural keys: department/machine name, material code, product name, order no.):
- 6 machines (Press 01, CNC 01, CNC 02, Assembly 2, Rolling 01, QC) with 8-16 h/day, labour departments,
  machine and labour rates; Sundays are off (the calendar rule in the engine).
- multi-step routes with setup hours and minutes per piece, BOMs, stock and incoming material.
- 7 accepted candidate orders in Orders received: 4 sent to Planning (ticked) and 3 not.
- running (in production / already planned) orders that hold machines for the first days.

Margins are NOT stored: the screens compute them from (value - cost) / value. To land near the demo's
illustrative targets, the material price per unit is derived here from each order's value and the
conversion cost the engine will compute (machine + labour hours, overhead %, packaging).
"""

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401  (every table known to SQLAlchemy, for the standalone command)
from app.catalog.models import Material, MaterialStock, Product, ProductMaterial
from app.core import clock
from app.core.config import get_settings
from app.core.db import set_tenant
from app.core.models import TenantSetting
from app.orders.models import Order
from app.planning.models import Department, Machine, RouteStep

# name, labour hours available per day, ₹ per labour hour
DEPARTMENTS = [("Machining", "96", 180), ("Assembly", "16", 170), ("Quality", "16", 200)]

# name, department, hours/shift, shifts/day, operators, ₹/h machine+power, ₹/h night premium, inspection
MACHINES = [
    ("Press 01", "Machining", 8, 2, 2, 650, 1_150, False),
    ("CNC 01", "Machining", 8, 2, 1, 900, 1_150, False),
    ("CNC 02", "Machining", 8, 1, 1, 800, 1_100, False),
    ("Assembly 2", "Assembly", 8, 1, 2, 400, 800, False),
    ("Rolling 01", "Machining", 8, 2, 1, 500, 900, False),
    ("QC", "Quality", 8, 1, 2, 300, 600, True),
]

# product -> [(machine, setup hours, minutes per piece)]  (operation hours = setup + qty x min / 60)
ROUTES: dict[str, list[tuple[str, str, str]]] = {
    "Anchor bolts M20": [("CNC 01", "2", "0.050"), ("Rolling 01", "1", "0.040")],
    "M16 hex nuts": [("CNC 01", "2", "0.025"), ("Press 01", "1", "0.012")],
    "Wheel studs": [("Rolling 01", "2", "0.060"), ("QC", "0", "0.006")],
    "M10 hex bolts": [("CNC 01", "2", "0.150"), ("QC", "0", "0.010")],
    "M12 flange bolts": [("Press 01", "2", "0.050"), ("QC", "0", "0.004")],
    "M8 nylock nuts": [("Press 01", "2", "0.008"), ("CNC 01", "1", "0.006")],
    "Tie rod ends": [("Assembly 2", "1", "0.600")],
    "M6 socket screws": [("CNC 02", "1", "0.030")],
    "Spring washers": [("Press 01", "1", "0.004")],
    "U-bolts": [("Press 01", "2", "0.100"), ("Rolling 01", "1", "0.060")],
}

# product -> (material code, material name, unit, quantity of material per piece)
BOMS: dict[str, tuple[str, str, str, str]] = {
    "M8 nylock nuts": ("WR8", "Steel wire rod", "t", "0.000025"),
    "M10 hex bolts": ("BSW", "Boron steel wire", "t", "0.000045"),
    "M16 hex nuts": ("MSB", "MS bright bar", "t", "0.00006"),
    "Spring washers": ("SPS", "Spring steel strip", "t", "0.000004"),
    "M6 socket screws": ("AS10", "Alloy steel wire 10.9", "t", "0.00002"),
    "Tie rod ends": ("TRK", "Tie rod kits (bought-out)", "sets", "1"),
    "U-bolts": ("EN8", "EN8 steel", "t", "0.0006"),
}

# material code -> (on hand, arrives in N days or None, qty arriving, express ₹, express days, supplier)
STOCK: dict[str, tuple[str, int | None, str, int, int, str]] = {
    "WR8": ("0.6", None, "0", 6_200, 3, "Shree Steels"),  # 3 t needed for ORD-1041: a real shortage
    "BSW": ("12.0", None, "0", 7_500, 2, "Mukand Wires"),
    "MSB": ("8.0", None, "0", 6_000, 2, "Shree Steels"),
    "SPS": ("2.0", None, "0", 5_000, 2, "Jindal Strips"),
    "AS10": ("4.0", None, "0", 7_000, 2, "Mukand Wires"),
    "TRK": ("5000", None, "0", 9_000, 2, "Rane Components"),
    "EN8": ("3.0", 6, "8.0", 8_000, 3, "Shree Steels"),
}

# The 7 accepted candidates: order no. -> (sent to Planning?, illustrative margin target)
CANDIDATES: dict[str, tuple[bool, float]] = {
    "ORD-1037": (True, 0.25),  # Tie rod ends, Assembly 2: starts day 1 next to the running orders
    "ORD-1041": (True, 0.22),  # M8 nylock nuts, Press 01 -> CNC 01: short of steel wire rod
    "ORD-1040": (True, 0.28),  # M10 hex bolts, CNC 01 -> QC: competes for CNC 01
    "ORD-1044": (True, 0.18),  # M16 hex nuts, CNC 01 -> Press 01: competes for CNC 01
    "ORD-1035": (False, 0.13),  # U-bolts: low margin, waits for EN8 -> Excluded
    "ORD-1036": (False, 0.26),  # M6 socket screws on idle CNC 02 -> Suggested
    "ORD-1043": (False, 0.24),  # Spring washers on Press 01 -> Suggested
}
# Running (locked) orders: order no. -> (status, progress %)
RUNNING = {
    "ORD-1033": ("in_production", 40),
    "ORD-1034": ("in_production", 50),
    "ORD-1038": ("in_production", 30),
    "ORD-1042": ("in_production", 85),
    "ORD-1039": ("planned", 0),
}
# Bump when the scenario above changes: dev startup then re-applies it ONCE to old demo databases.
DEMO_VERSION = 3
VERSION_KEY = "seed.planning-demo"

# Company rule defaults (planning-rules), used only to derive the demo material prices.
OVERHEAD_PCT = 7.0
PACKAGING_PAISE = 5


async def upsert(s: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Make the planning demo exactly as described above. Safe to run again and again."""
    await set_tenant(s, tenant_id)
    today = clock.today()

    depts: dict[str, Department] = {}
    for name, hrs, rate in DEPARTMENTS:
        d = (
            await s.execute(
                select(Department).where(Department.tenant_id == tenant_id, Department.name == name)
            )
        ).scalar_one_or_none()
        if d is None:
            d = Department(name=name, hours_per_day=Decimal(hrs), cost_per_hour_paise=rate * 100)
            s.add(d)
        d.hours_per_day, d.cost_per_hour_paise = Decimal(hrs), rate * 100
        depts[name] = d
    await s.flush()

    machines: dict[str, Machine] = {}
    for i, (name, dept, shift_hrs, shifts, ops, rate, night, insp) in enumerate(MACHINES):
        m = (
            await s.execute(select(Machine).where(Machine.tenant_id == tenant_id, Machine.name == name))
        ).scalar_one_or_none()
        if m is None:
            m = Machine(
                name=name,
                department_id=depts[dept].id,
                hours_per_shift=Decimal(shift_hrs),
                cost_per_hour_paise=0,
            )
            s.add(m)
        m.department_id, m.hours_per_shift, m.shifts_per_day, m.operators = (
            depts[dept].id,
            Decimal(shift_hrs),
            shifts,
            ops,
        )
        m.cost_per_hour_paise, m.night_shift_cost_per_hour_paise = rate * 100, night * 100
        m.inspection, m.sort, m.active = insp, i, True
        machines[name] = m
    await s.flush()

    products = {
        p.name: p for p in (await s.execute(select(Product).where(Product.tenant_id == tenant_id))).scalars()
    }
    for pname, steps in ROUTES.items():
        p = products[pname]
        await s.execute(
            delete(RouteStep).where(RouteStep.tenant_id == tenant_id, RouteStep.product_id == p.id)
        )
        for seq, (mname, setup, mins) in enumerate(steps, start=1):
            s.add(RouteStep(product_id=p.id, seq=seq, machine_id=machines[mname].id,
                            setup_hours=Decimal(setup), minutes_per_unit=Decimal(mins)))  # fmt: skip
    await s.flush()

    materials: dict[str, Material] = {}
    for pname, (code, mname, unit, per_pc) in BOMS.items():
        mat = (
            await s.execute(select(Material).where(Material.tenant_id == tenant_id, Material.code == code))
        ).scalar_one_or_none()
        if mat is None:
            mat = Material(code=code, name=mname, unit=unit)
            s.add(mat)
            await s.flush()
        mat.name, mat.unit = mname, unit
        materials[code] = mat
        await s.execute(
            delete(ProductMaterial).where(
                ProductMaterial.tenant_id == tenant_id, ProductMaterial.product_id == products[pname].id
            )
        )
        s.add(
            ProductMaterial(product_id=products[pname].id, material_id=mat.id, qty_per_unit=Decimal(per_pc))
        )
        on_hand, arrive_in, arriving, exp, exp_days, supplier = STOCK[code]
        st = (
            await s.execute(
                select(MaterialStock).where(
                    MaterialStock.tenant_id == tenant_id, MaterialStock.material_id == mat.id
                )
            )
        ).scalar_one_or_none()
        if st is None:
            st = MaterialStock(material_id=mat.id)
            s.add(st)
        st.on_hand = Decimal(on_hand)
        st.next_arrival_date = today + timedelta(days=arrive_in) if arrive_in else None
        st.next_arrival_qty = Decimal(arriving) if arrive_in else None
        mat.express_cost_paise, mat.express_days, mat.express_supplier = exp * 100, exp_days, supplier
    await s.flush()

    orders = {o.number: o for o in (await s.execute(select(Order).where(Order.tenant_id == tenant_id, Order.number.in_([*CANDIDATES, *RUNNING])))).scalars()}  # fmt: skip
    for num, (status, progress) in RUNNING.items():
        o = orders[num]
        o.status, o.progress_pct, o.marked_for_planning = (
            status,
            progress if status == "in_production" else None,
            False,
        )
    dept_rate = {d.id: d.cost_per_hour_paise for d in depts.values()}
    for num, (marked, margin) in CANDIDATES.items():
        o = orders[num]
        o.status, o.marked_for_planning, o.progress_pct, o.promised_date = "accepted", marked, None, None
        # Derive the material price so (value - cost) / value lands near the demo target.
        pname = next(p for p in products.values() if p.id == o.product_id).name
        conv = 0.0
        for step_machine, setup, mins in ROUTES[pname]:
            mc = machines[step_machine]
            op_hrs = float(setup) + float(o.quantity) * float(mins) / 60
            conv += op_hrs * mc.cost_per_hour_paise + op_hrs * mc.operators * dept_rate[mc.department_id]
        target_cost = o.sales_paise * (1 - margin)
        mat_cost = (target_cost - float(o.quantity) * PACKAGING_PAISE) / (1 + OVERHEAD_PCT / 100) - conv
        bom_code, _, _, bom_qty = BOMS[pname]
        units = float(o.quantity) * float(bom_qty)
        materials[bom_code].price_per_unit_paise = max(0, round(mat_cost / units))
    await _set_version(s, tenant_id, DEMO_VERSION)
    await s.flush()
    return {"machines": len(machines), "candidates": len(CANDIDATES), "running": len(RUNNING)}


async def _version(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    row = (
        await s.execute(
            select(TenantSetting).where(
                TenantSetting.tenant_id == tenant_id, TenantSetting.key == VERSION_KEY
            )
        )
    ).scalar_one_or_none()
    return int(row.value.get("version", 0)) if row else 0


async def _set_version(s: AsyncSession, tenant_id: uuid.UUID, version: int) -> None:
    row = (
        await s.execute(
            select(TenantSetting).where(
                TenantSetting.tenant_id == tenant_id, TenantSetting.key == VERSION_KEY
            )
        )
    ).scalar_one_or_none()
    if row is None:
        s.add(TenantSetting(key=VERSION_KEY, value={"version": version}))
    else:
        row.value = {"version": version}


async def is_demo_company(s: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """The company still has every demo order and product the scenario is built on."""
    nums = [*CANDIDATES, *RUNNING]
    found = (
        await s.execute(select(Order.number).where(Order.tenant_id == tenant_id, Order.number.in_(nums)))
    ).scalars()
    names = (
        await s.execute(
            select(Product.name).where(Product.tenant_id == tenant_id, Product.name.in_(list(ROUTES)))
        )
    ).scalars()
    return set(found) == set(nums) and set(names) == set(ROUTES)


async def upgrade_if_old(s: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """Apply the scenario once to a demo database seeded before DEMO_VERSION (dev startup only).

    Skipped when the company is already on this version (so the owner's later ticks and edits are kept)
    or when it does not hold the demo orders/products (a real company is never touched).
    """
    await set_tenant(s, tenant_id)
    if await _version(s, tenant_id) >= DEMO_VERSION or not await is_demo_company(s, tenant_id):
        return False
    await upsert(s, tenant_id)
    return True


async def main() -> None:
    from app.core.models import Tenant

    engine = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(engine)() as s, s.begin():
        tenants = list((await s.execute(select(Tenant))).scalars())
        for t in tenants:
            await set_tenant(s, t.id)
            # The seed role is a superuser (RLS does not filter it): check this company has the demo orders.
            has = (
                await s.execute(select(Order.id).where(Order.tenant_id == t.id, Order.number == "ORD-1037"))
            ).first()
            if has:
                print(t.slug, await upsert(s, t.id))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""Demo purchase orders at every stage (Raw Material Purchase) and 6 months of supplier history, quotes and
a pending quote request (Supplier comparison). Dev seed only.

Kept out of `planning_demo.upsert` (which tests reuse) so the planning and inventory demos keep their numbers:
the POs below only touch materials the demo plan has plenty of (or are not approved yet), so Planning's
schedule doesn't change. The seed role bypasses RLS: everything is filtered by `tenant_id` explicitly.
Idempotent: skipped when the company already has these demo POs (source "demo_buy").
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Material
from app.core import clock, counters
from app.core.db import set_tenant
from app.purchasing.models import PoEvent, PurchaseOrder, PurchaseOrderLine, Supplier, SupplierQuote

SOURCE = "demo_buy"

# material, supplier, qty, status, expected in N days, linked orders, priority (no order), steps done
SCENARIO: list[tuple[str, str, str, str, int, list[str], str | None]] = [
    # waits for the owner: WR8 for ORD-1041 (the shortage on the Inventory tab)
    ("WR8", "JSW Steel Distributors", "2.4", "awaiting_approval", 3, ["ORD-1041"], None),
    # dispatched, due yesterday: delayed
    ("BSW", "Mukand Wires", "3.0", "dispatched", -1, ["ORD-1040"], None),
    # arrived today: gate entry logged, waiting for QC
    ("MSB", "Shree Steels", "2.0", "at_gate", 0, ["ORD-1044"], None),
    # approved and sent, no supplier date yet
    ("AS10", "Mukand Wires", "1.5", "ordered", 8, [], "medium"),
]


# Supplier history for Supplier comparison (received POs over the last 6 months):
# material, supplier, rate vs the material's price, lead days, deliveries, how many late, % rejected at QC
HISTORY: list[tuple[str, str, float, int, int, int, float]] = [
    ("WR8", "JSW Steel Distributors", 0.98, 3, 8, 0, 0.004),
    ("WR8", "Tata Steel BSL", 1.02, 4, 6, 0, 0.001),
    ("WR8", "Jindal Stainless & Wire", 0.95, 6, 6, 2, 0.012),
    ("BSW", "Mukand Wires", 1.00, 4, 6, 1, 0.005),
    ("BSW", "Bhushan Steel", 0.97, 7, 4, 2, 0.008),
    ("MSB", "Shree Steels", 1.00, 4, 6, 0, 0.003),
    ("MSB", "Arcturus Steel", 0.94, 7, 3, 1, 0.015),
    ("AS10", "Nippon Steel India", 1.05, 5, 4, 0, 0.002),
    ("AS10", "Mukand Wires", 1.00, 5, 3, 0, 0.004),
    ("SPS", "Jindal Strips", 1.00, 4, 5, 1, 0.006),
    ("TRK", "Rane Components", 1.00, 5, 5, 0, 0.002),
]
# quotes received (valid for 3 more weeks): material, supplier, rate vs price, quoted lead days
QUOTES: list[tuple[str, str, float, int]] = [
    ("WR8", "JSW Steel Distributors", 0.98, 3),
    ("WR8", "Tata Steel BSL", 1.03, 4),
    ("WR8", "Jindal Stainless & Wire", 0.94, 6),
    ("SPS", "Jindal Strips", 1.01, 4),
]
# asked, no reply yet: material, supplier
ASKED: list[tuple[str, str]] = [("SPS", "Shyam Steel")]


async def _supplier(s: AsyncSession, tenant_id: uuid.UUID, name: str) -> Supplier:
    sup = (await s.execute(select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.name == name))
           ).scalar_one_or_none()  # fmt: skip
    if sup is None:
        sup = Supplier(name=name)
        s.add(sup)
        await s.flush()
    return sup


async def _history(s: AsyncSession, tenant_id: uuid.UUID, mats: dict[str, Material]) -> int:
    """Received POs with gate entries and QC, spread over the last 6 months (no stock movements: the opening
    balances already include them)."""
    now = datetime.now(UTC)
    rows = []
    for code, supplier, k, lead, n, late, rej in HISTORY:
        for i in range(n):
            arrived = now - timedelta(days=12 + (i * 160) // max(n, 1) + len(supplier) % 5)
            rows.append((arrived, code, supplier, k, lead, i < late, rej))
    made = 0
    for arrived, code, supplier, k, lead, is_late, rej in sorted(rows):
        mat = mats.get(code)
        if mat is None:
            continue
        sup = await _supplier(s, tenant_id, supplier)
        approved = arrived - timedelta(days=lead + (2 if is_late else 0))
        promised = (approved + timedelta(days=lead)).date()
        q = Decimal("2.0") if mat.unit == "t" else Decimal("1000")
        bad = (q * Decimal(str(rej)) * 5).quantize(Decimal("0.001")) if rej and made % 5 == 0 else Decimal(0)
        n = await counters.next_value(s, "po", start=0)
        po = PurchaseOrder(number=f"PO-{n:04d}", supplier_id=sup.id, status="received", source=SOURCE,
                           expected_date=promised, promised_date=promised, confirmed=True, approved_at=approved,
                           note="Demo history", created_at=approved - timedelta(days=1))  # fmt: skip
        s.add(po)
        await s.flush()
        s.add(PurchaseOrderLine(po_id=po.id, material_id=mat.id, quantity=q, unit=mat.unit,
                                price_per_unit_paise=round(mat.price_per_unit_paise * k), received_qty=q,
                                rejected_qty=bad))  # fmt: skip
        steps = [("raised", "Raised", approved - timedelta(days=1), {}),
                 ("approved", "Approved by the owner · PO sent to the supplier", approved, {}),
                 ("gate_entry", f"Gate entry · {q} {mat.unit} · GRN-{n:04d}", arrived, {"qty": str(q), "ref": f"GRN-{n:04d}"}),
                 ("qc", f"QC · {q - bad} {mat.unit} accepted", arrived + timedelta(hours=3),
                  {"accepted": str(q - bad), "rejected": str(bad)})]  # fmt: skip
        if bad:  # the rejected part was replaced two days later
            steps += [("gate_entry", f"Gate entry · {bad} {mat.unit} (replacement)", arrived + timedelta(days=2),
                       {"qty": str(bad)}),
                      ("qc", f"QC · {bad} {mat.unit} accepted", arrived + timedelta(days=2, hours=3),
                       {"accepted": str(bad), "rejected": "0"})]  # fmt: skip
        for kind, summary, at, data in steps:
            s.add(PoEvent(po_id=po.id, kind=kind, summary=summary, data=data, created_at=at))
        made += 1
    today = clock.today()
    for code, supplier, k, lead in QUOTES:
        mat = mats.get(code)
        if mat is not None:
            sup = await _supplier(s, tenant_id, supplier)
            s.add(SupplierQuote(supplier_id=sup.id, material_id=mat.id, status="received",
                                rate_paise=round(mat.price_per_unit_paise * k), lead_days=lead,
                                valid_until=today + timedelta(days=21), replied_at=datetime.now(UTC),
                                note="Demo data"))  # fmt: skip
    for code, supplier in ASKED:
        mat = mats.get(code)
        if mat is not None:
            sup = await _supplier(s, tenant_id, supplier)
            s.add(SupplierQuote(supplier_id=sup.id, material_id=mat.id, status="requested", quantity=Decimal("2"),
                                note="Demo data"))  # fmt: skip
    await s.flush()
    return made


async def seed_purchases(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    await set_tenant(s, tenant_id)
    done = (await s.execute(select(PurchaseOrder.id).where(PurchaseOrder.tenant_id == tenant_id,
                                                           PurchaseOrder.source == SOURCE))).first()  # fmt: skip
    if done is not None:
        return 0
    mats = {
        m.code: m
        for m in (await s.execute(select(Material).where(Material.tenant_id == tenant_id))).scalars()
    }
    await _history(s, tenant_id, mats)  # older, so it gets the lower PO numbers
    today, now = clock.today(), datetime.now(UTC)
    n_made = 0
    for code, supplier, qty, status, days, orders, prio in SCENARIO:
        mat = mats.get(code)
        if mat is None:
            continue
        sup = await _supplier(s, tenant_id, supplier)
        n = await counters.next_value(s, "po", start=0)
        q = Decimal(qty)
        po = PurchaseOrder(number=f"PO-{n:04d}", supplier_id=sup.id, status=status,
                           expected_date=today + timedelta(days=days), source=SOURCE, note="Demo data",
                           order_numbers=orders, priority=prio)  # fmt: skip
        s.add(po)
        await s.flush()
        s.add(PurchaseOrderLine(po_id=po.id, material_id=mat.id, quantity=q, unit=mat.unit,
                                price_per_unit_paise=mat.price_per_unit_paise, received_qty=Decimal(0),
                                rejected_qty=Decimal(0)))  # fmt: skip
        steps = [("raised", f"Raised · {qty} {mat.unit} {mat.name} from {supplier}", 6)]
        if status != "awaiting_approval":
            po.approved_at = now - timedelta(days=5)
            po.promised_date = po.expected_date
            steps.append(("approved", "Approved by the owner · PO sent to the supplier", 5))
        if status in ("dispatched", "at_gate"):
            po.confirmed = True
            steps.append(("confirmed", f"Supplier confirmed delivery {po.expected_date:%a %-d %b}", 4))
            po.dispatched_at = now - timedelta(days=2)
            steps.append(("dispatched", f"Dispatched · arriving {po.expected_date:%a %-d %b}", 2))
        if status == "at_gate":
            po.gate_qty, po.gate_ref, po.gate_at = q, "CH-4471 / MH14 GT 2210", now
            steps.append(("gate_entry", f"Gate entry · {qty} {mat.unit} · {po.gate_ref}", 0))
        for kind, summary, ago in steps:
            s.add(
                PoEvent(
                    po_id=po.id,
                    kind=kind,
                    summary=summary,
                    created_at=now - timedelta(days=ago),
                    data={"ref": po.gate_ref} if kind == "gate_entry" else {},
                )
            )
        n_made += 1
    await s.flush()
    from app.purchasing.service import sync_incoming

    await sync_incoming(s, {m.id for m in mats.values()})
    return n_made

# mypy: disable-error-code="assignment,attr-defined,misc,arg-type,unused-ignore,operator"
# (Demo data script: loose typing is fine here; app code is strictly typed.)
"""Demo business data for the seeded companies. Dates are relative to today so the
screens always look current. Deterministic (fixed random seed)."""

import random
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Material, MaterialStock, Product, ProductMaterial
from app.core import clock, counters
from app.core.db import set_tenant
from app.core.gst import STATE_CODES, financial_year, gstin_checksum
from app.customers.models import Customer, CustomerAddress, CustomerContact, CustomerFollowup
from app.invoices.models import Invoice, InvoiceLine, InvoiceParty
from app.orders.models import Order

SELLER_STATE = "27"
SELLER_GSTIN = "27AAFCD5512K1Z" + gstin_checksum("27AAFCD5512K1Z")


def gst(state: str, pan: str) -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_checksum(body)


def paise(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# sku, name, processing days, price (paise/pc), cost (paise/pc), [(material, t per pc)]
PRODUCTS = [
    ("M10-HEX", "M10 hex bolts", 4, 10_000, 9_000, [("BSW", "0.000045")]),
    ("M8-NYL", "M8 nylock nuts", 4, 1_533, 1_358, [("WR8", "0.000025")]),
    ("M12-FLG", "M12 flange bolts", 3, 9_200, 8_100, [("EN8", "0.00008")]),
    ("WSTUD", "Wheel studs", 5, 5_500, 4_900, [("EN8", "0.00012")]),
    ("M6-SKT", "M6 socket screws", 3, 1_633, 1_433, [("EN8", "0.00002")]),
    ("UBOLT", "U-bolts", 4, 17_750, 15_375, [("EN8", "0.0006")]),
    ("M16-HN", "M16 hex nuts", 3, 1_200, 1_020, [("MSB", "0.00006")]),
    ("SPWASH", "Spring washers", 2, 150, 118, [("SPS", "0.000004")]),
    ("TROD", "Tie rod ends", 6, 21_000, 18_500, [("EN8", "0.0009")]),
    ("ANCB", "Anchor bolts M20", 4, 6_500, 5_600, [("BSW", "0.00025")]),
]
# code, name, on hand (t), next arrival in N days
MATERIALS = [
    ("WR8", "Steel wire rod", "0.6", None),
    ("EN8", "EN8 steel", "3.0", 6),
    ("BSW", "Boron steel wire", "12.0", None),
    ("MSB", "MS bright bar", "8.0", None),
    ("SPS", "Spring steel strip", "2.0", None),
]

# name, state, PAN, tier, profile, city
CUSTOMERS = [
    ("Maruti Suzuki", "06", "AAACM1234A", "key", "hv", "Gurugram"),
    ("Tata Motors", "27", "AAACT2727Q", "key", "hv", "Pune"),
    ("Mahindra", "27", "AAACM5678C", "key", "hv", "Mumbai"),
    ("Bajaj Auto", "27", "AAACB2345D", "key", "regular", "Pune"),
    ("Hero MotoCorp", "07", "AAACH3456E", "standard", "regular", "New Delhi"),
    ("Ashok Leyland", "33", "AAACA4567F", "standard", "declining", "Chennai"),
    ("Escorts Kubota", "06", "AAACE6789H", "standard", "new", "Faridabad"),
    ("TVS Motor", "33", "AAACT5678G", "standard", "inactive", "Hosur"),
    ("Eicher Motors", "23", "AAACE1122K", "standard", "regular", "Pithampur"),
    ("Force Motors", "27", "AAACF3344L", "standard", "regular", "Pune"),
    ("Royal Enfield", "33", "AAACR5566M", "standard", "declining", "Chennai"),
    ("Sonalika Tractors", "03", "AAACS7788N", "standard", "regular", "Hoshiarpur"),
    ("JCB India", "06", "AAACJ9900P", "standard", "regular", "Ballabgarh"),
    ("Bharat Forge", "27", "AAACB1212Q", "key", "regular", "Pune"),
]
SMALL = [
    ("Shree Krishna Auto Parts", "27", "Pune"), ("Vardhman Engineering Works", "03", "Ludhiana"),
    ("Pune Precision Components", "27", "Pune"), ("Deccan Tractor Spares", "36", "Hyderabad"),
    ("Kolhapur Castings Pvt Ltd", "27", "Kolhapur"), ("Nashik Agro Implements", "27", "Nashik"),
    ("Aurangabad Auto Ancillary", "27", "Aurangabad"), ("Satara Forgings", "27", "Satara"),
    ("Ludhiana Cycle Components", "03", "Ludhiana"), ("Rajkot Engineering Co", "24", "Rajkot"),
    ("Coimbatore Pump Industries", "33", "Coimbatore"), ("Hosur Auto Components", "33", "Hosur"),
    ("Chakan Sheet Metal Works", "27", "Chakan"), ("Faridabad Fasteners Trading", "06", "Faridabad"),
    ("Jamshedpur Heavy Engineering", "20", "Jamshedpur"), ("Gurgaon Auto Tech", "06", "Gurugram"),
    ("Indore Agri Machines", "23", "Indore"), ("Vapi Process Equipment", "24", "Vapi"),
    ("Bhosari Tool Room", "27", "Pune"), ("Sanand Auto Systems", "24", "Sanand"),
    ("Ranjangaon Assemblies", "27", "Ranjangaon"), ("Talegaon Industrial Supplies", "27", "Talegaon"),
    ("Ambattur Engineering", "33", "Chennai"), ("Peenya Motor Parts", "29", "Bengaluru"),
]  # fmt: skip
SMALL_PROFILES = ["regular", "regular", "dormant", "inactive", "regular", "dormant", "occasional", "regular",
                  "dormant", "regular", "declining", "regular", "new", "occasional", "dormant", "regular",
                  "inactive", "regular", "never", "regular", "occasional", "never", "regular", "inactive"]  # fmt: skip


@dataclass
class Cust:
    id: uuid.UUID
    name: str
    state: str
    gstin: str
    profile: str
    tier: str


async def seed_demo(s: AsyncSession, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    await set_tenant(s, tenant_id)
    rng = random.Random(20261113)
    today = clock.today()

    # ---- catalog ------------------------------------------------------------------------
    mats = {}
    for code, name, on_hand, arrival_in in MATERIALS:
        m = Material(code=code, name=name, unit="t")
        s.add(m)
        await s.flush()
        mats[code] = m
        s.add(MaterialStock(material_id=m.id, on_hand=Decimal(on_hand),
                            next_arrival_date=today + timedelta(days=arrival_in) if arrival_in else None,
                            next_arrival_qty=Decimal("8") if arrival_in else None))  # fmt: skip
    prods = {}
    for sku, name, days, price, cost, bom in PRODUCTS:
        p = Product(sku=sku, name=name, unit="pcs", hsn="7318", processing_days=days, unit_price_paise=price,
                    unit_cost_paise=cost)  # fmt: skip
        s.add(p)
        await s.flush()
        prods[name] = p
        for code, q in bom:
            s.add(ProductMaterial(product_id=p.id, material_id=mats[code].id, qty_per_unit=Decimal(q)))

    # ---- customers ------------------------------------------------------------------------
    custs: dict[str, Cust] = {}
    all_rows = [(n, st, pan, tier, prof, city) for n, st, pan, tier, prof, city in CUSTOMERS]
    for i, (n, st, city) in enumerate(SMALL):
        pan = (
            "AA"
            + rng.choice("ABFH")
            + "C"
            + n[0].upper()
            + f"{rng.randint(1000, 9999)}"
            + rng.choice(string.ascii_uppercase)
        )
        all_rows.append((n, st, pan, "occasional" if SMALL_PROFILES[i] in ("occasional", "dormant") else "standard",
                         SMALL_PROFILES[i], city))  # fmt: skip
    for n, st, pan, tier, prof, city in all_rows:
        g = gst(st, pan)
        slug = "".join(ch for ch in n.lower() if ch.isalnum())[:14]
        c = Customer(name=n, gstin=g, pan=pan, state_code=st, tier=tier, phone=f"+91 9{rng.randint(100000000, 999999999)}",
                     email=f"purchase@{slug}.example", payment_terms_days=rng.choice([30, 45, 60]),
                     credit_limit_paise=rng.choice([25, 50, 100, 200]) * 100_000_00,
                     tags=["automotive"] if tier == "key" else [])  # fmt: skip
        s.add(c)
        await s.flush()
        s.add(CustomerAddress(customer_id=c.id, kind="billing", line1=f"Plant {rng.randint(1, 9)}, Industrial Area",
                              city=city, state_code=st, pincode=f"{rng.randint(110001, 699999)}"))  # fmt: skip
        s.add(CustomerContact(customer_id=c.id, name=rng.choice(["R. Kulkarni", "S. Iyer", "A. Sharma", "P. Nair",
                                                                  "M. Joshi", "K. Reddy", "V. Singh", "N. Patil"]),
                              designation="Purchase Manager", phone=c.phone, email=c.email, is_primary=True))  # fmt: skip
        custs[n] = Cust(c.id, n, st, g, prof, tier)

    # ---- invoices (15 months of history) -----------------------------------------------------
    start = today - timedelta(days=455)
    plans: list[tuple[Cust, date]] = []
    for c in custs.values():
        prof = c.profile
        if prof == "never":
            continue
        if prof == "hv":
            gaps, last_gap = (9, 16), rng.randint(1, 6)
        elif prof == "regular":
            gaps, last_gap = (24, 30), rng.randint(2, 30)
        elif prof == "declining":
            gaps, last_gap = (14, 22), rng.randint(15, 30)
        elif prof == "inactive":
            gaps, last_gap = (20, 30), rng.randint(64, 86) if c.name != "TVS Motor" else 78
        elif prof == "dormant":
            gaps, last_gap = (25, 45), rng.randint(110, 300)
        elif prof == "occasional":
            gaps, last_gap = (60, 110), rng.randint(20, 55)
        else:  # new
            gaps, last_gap = (5, 9), rng.randint(3, 12)
        d = today - timedelta(days=last_gap)
        first_allowed = today - timedelta(days=40) if prof == "new" else start
        dates = []
        while d >= first_allowed:
            dates.append(d)
            gap = rng.randint(*gaps)
            if prof == "declining" and d > today - timedelta(days=200):
                gap *= 3  # buys much less often lately
            d -= timedelta(days=gap)
        plans += [(c, x) for x in sorted(dates)]
    plans.sort(key=lambda t: t[1])

    seq: dict[str, int] = {}
    names = list(prods)
    big = {"hv": (9, 12), "regular": (3, 4), "declining": (5, 7), "inactive": (2, 3), "dormant": (1, 3),
           "occasional": (1, 2), "new": (3, 6)}  # fmt: skip
    invoices: list[tuple[Invoice, Cust, str, Decimal]] = []
    for c, d in plans:
        fy = financial_year(d)
        seq[fy] = seq.get(fy, 0) + 1
        prod = (
            names[(hash(c.name) + d.toordinal()) % len(names)] if c.profile != "hv" else rng.choice(names[:6])
        )
        p = prods[prod]
        lo, hi = big[c.profile]
        if c.profile == "declining" and d > today - timedelta(days=200):
            lo, hi = max(1, lo // 3), max(2, hi // 3)
        target = Decimal(rng.randint(lo * 10, hi * 10)) * 10_000_00  # ₹1 L steps
        qty = (target / p.unit_price_paise).quantize(Decimal("100"), rounding=ROUND_HALF_UP) or Decimal(100)
        taxable = paise(qty * p.unit_price_paise)
        intra = c.state == SELLER_STATE
        tax = paise(Decimal(taxable) * Decimal("0.18"))
        cg = sg = paise(Decimal(taxable) * Decimal("0.09")) if intra else 0
        ig = 0 if intra else tax
        gross = taxable + cg + sg + ig
        grand = paise(Decimal(gross) / 100) * 100
        age = (today - d).days
        if age <= 30:
            balance = grand
        elif age <= 60:
            balance = grand if rng.random() < 0.45 else (grand // 2 if rng.random() < 0.3 else 0)
        else:
            balance = grand // 4 if rng.random() < 0.06 else 0
        inv = Invoice(source="seed", customer_id=c.id, invoice_number=f"DMC/{fy}/{seq[fy]:04d}", invoice_date=d,
                      invoice_type="tax_invoice", due_date=d + timedelta(days=30), financial_year=fy,
                      seller_gstin=SELLER_GSTIN, buyer_gstin=c.gstin, total_quantity=qty, total_taxable_paise=taxable,
                      total_cgst_paise=cg or None, total_sgst_paise=sg or None, total_igst_paise=ig or None,
                      round_off_paise=grand - gross, grand_total_paise=grand, amount_paid_paise=grand - balance,
                      balance_due_paise=balance, place_of_supply_code=c.state,
                      place_of_supply=STATE_CODES[c.state], supply_type="intra" if intra else "inter")  # fmt: skip
        s.add(inv)
        invoices.append((inv, c, prod, qty))
    await s.flush()
    for inv, c, prod, qty in invoices:
        p = prods[prod]
        s.add(InvoiceLine(invoice_id=inv.id, line_no=1, product_id=p.id, product_name=prod, hsn="7318", quantity=qty,
                          uom="PCS", unit_price_paise=p.unit_price_paise, taxable_paise=inv.total_taxable_paise,
                          gst_rate=Decimal(18), cgst_paise=inv.total_cgst_paise, sgst_paise=inv.total_sgst_paise,
                          igst_paise=inv.total_igst_paise,
                          total_paise=(inv.total_taxable_paise or 0) + (inv.total_cgst_paise or 0)
                          + (inv.total_sgst_paise or 0) + (inv.total_igst_paise or 0)))  # fmt: skip
        s.add(InvoiceParty(invoice_id=inv.id, role="seller", name="Demo Manufacturing Co.", gstin=SELLER_GSTIN,
                           state="Maharashtra", state_code=SELLER_STATE))  # fmt: skip
        s.add(InvoiceParty(invoice_id=inv.id, role="buyer", name=c.name, gstin=c.gstin, state=STATE_CODES[c.state],
                           state_code=c.state))  # fmt: skip

    # ---- past orders (one per recent big invoice) --------------------------------------------
    past = [
        t
        for t in invoices
        if t[0].invoice_date and today - timedelta(days=150) < t[0].invoice_date < today - timedelta(days=12)
    ]
    past = sorted(rng.sample(past, min(30, len(past))), key=lambda t: t[0].invoice_date)  # type: ignore[arg-type,return-value]
    number = 1001
    for inv, c, prod, qty in past:
        p = prods[prod]
        cancelled = number in (1009, 1021)
        o = Order(number=f"ORD-{number}", customer_id=c.id, product_id=p.id, quantity=qty, unit="pcs",
                  unit_price_paise=p.unit_price_paise, sales_paise=paise(qty * p.unit_price_paise),
                  cost_paise=paise(qty * p.unit_cost_paise), processing_days=p.processing_days,
                  ship_date=inv.invoice_date, priority=rng.choice(["high", "medium", "medium", "low"]),  # type: ignore[arg-type]
                  status="cancelled" if cancelled else ("shipped" if rng.random() < 0.8 else "completed"),
                  cancel_reason="Customer postponed the requirement" if cancelled else None,
                  closed_at=datetime.combine(inv.invoice_date, datetime.min.time(), UTC))  # type: ignore[arg-type]  # fmt: skip
        s.add(o)
        await s.flush()
        o.created_at = datetime.combine(inv.invoice_date - timedelta(days=12), datetime.min.time(), UTC)  # type: ignore[operator]
        if not cancelled:
            inv.order_id = o.id
        number += 1
    number = max(number, 1033)

    # ---- the current order book (matches the Orders mockup) --------------------------------------
    def wd(n: int) -> date:  # n days from today
        return today + timedelta(days=n)

    book = [
        # number, customer, product, qty, sales ₹, profit ₹, ship in, priority, status, progress
        (1033, "Bharat Forge", "Anchor bolts M20", 24_000, 15_60_000, 1_92_000, 4, "medium", "in_production", 70),
        (1034, "Force Motors", "M16 hex nuts", 90_000, 10_80_000, 1_35_000, 9, "medium", "in_production", 40),
        (1035, "Ashok Leyland", "U-bolts", 8_000, 14_20_000, 1_90_000, 14, "low", "new", None),
        (1036, "Hero MotoCorp", "M6 socket screws", 60_000, 9_80_000, 1_20_000, 11, "medium", "accepted", None),
        (1037, "Sonalika Tractors", "Tie rod ends", 2_000, 4_20_000, 50_000, 16, "low", "new", None),
        (1038, "Bajaj Auto", "Wheel studs", 40_000, 22_00_000, 2_40_000, 8, "medium", "in_production", 62),
        (1039, "Mahindra", "M12 flange bolts", 30_000, 27_60_000, 3_30_000, 6, "high", "planned", None),
        (1040, "Eicher Motors", "M10 hex bolts", 12_000, 12_00_000, 1_44_000, 13, "high", "accepted", None),
        (1041, "Tata Motors", "M8 nylock nuts", 1_20_000, 18_40_000, 2_10_000, 5, "high", "accepted", None),
        (1042, "Maruti Suzuki", "M10 hex bolts", 50_000, 50_00_000, 5_00_000, 3, "high", "in_production", 25),
        (1043, "JCB India", "Spring washers", 3_00_000, 4_50_000, 96_000, 12, "medium", "new", None),
        (1044, "Escorts Kubota", "M16 hex nuts", 75_000, 9_00_000, 1_17_000, 10, "high", "new", None),
    ]  # fmt: skip
    for num, cname, prod, qty, sales, profit, ship_in, prio, status, prog in book:
        p = prods[prod]
        q = Decimal(qty)
        o = Order(number=f"ORD-{num}", customer_id=custs[cname].id, product_id=p.id, quantity=q, unit="pcs",
                  unit_price_paise=paise(Decimal(sales * 100) / q),
                  sales_paise=paise(q * paise(Decimal(sales * 100) / q)),
                  cost_paise=paise(q * paise(Decimal((sales - profit) * 100) / q)), processing_days=p.processing_days, ship_date=wd(ship_in),
                  priority=prio, status=status, progress_pct=prog,
                  marked_for_planning=status == "accepted" and num in (1036, 1041))  # fmt: skip
        s.add(o)
        await s.flush()
        o.created_at = datetime.now(UTC) - timedelta(days=rng.randint(2, 15))
    await counters.ensure_at_least(s, "order", max(1044, number))

    # ---- follow-ups ---------------------------------------------------------------------------
    s.add(CustomerFollowup(customer_id=custs["TVS Motor"].id, kind="reminder", note="No orders since August. Call purchase head about Q4 schedule.",
                           due_date=today, assigned_to=owner_id, created_by=owner_id))  # fmt: skip
    s.add(CustomerFollowup(customer_id=custs["Ashok Leyland"].id, kind="call", note="Volumes down: they are trialling a second supplier.",
                           done_at=datetime.now(UTC) - timedelta(days=6), created_by=owner_id))  # fmt: skip


async def seed_second(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """A small second company, to show that companies never see each other's data."""
    await set_tenant(s, tenant_id)
    today = clock.today()
    p = Product(
        sku="CB-01", name="Carriage bolts", processing_days=3, unit_price_paise=800, unit_cost_paise=650
    )
    s.add(p)
    c = Customer(
        name="Kirloskar Pumps", gstin=gst("27", "AAACK4455R"), pan="AAACK4455R", state_code="27", tier="key"
    )
    s.add(c)
    await s.flush()
    s.add(Order(number="ORD-2001", customer_id=c.id, product_id=p.id, quantity=Decimal(5000), unit="pcs",
                unit_price_paise=800, sales_paise=4_000_000, cost_paise=3_250_000, processing_days=3,
                ship_date=today + timedelta(days=6), priority="high", status="new"))  # fmt: skip
    await counters.ensure_at_least(s, "order", 2001)

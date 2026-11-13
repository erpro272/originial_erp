"""Generate sample invoice files + matching mock-AI fixtures from ONE layout.

    uv run python -m scripts.make_sample_invoices

Writes samples/invoices/<name>.(pdf|jpg) (upload these to try the flow) and
app/ai/fixtures/invoice/<name>.json (what the mock AI returns for a file with that name).
Bounding boxes in the fixtures are where the text was drawn, so highlights line up.
"""

import base64
import io
import json
import random
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import segno
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.gst import gstin_checksum
from app.invoices.fields import FIELDS, LINE_FIELDS

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "invoices"
FIXTURES = ROOT / "backend" / "app" / "ai" / "fixtures" / "invoice"
W, H = 1240, 1754  # A4 at 150 dpi


def gst(state: str, pan: str) -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_checksum(body)


SELLER = {
    "seller_name": "Demo Manufacturing Co.",
    "seller_gstin": gst("27", "AAFCD5512K"),
    "seller_pan": "AAFCD5512K",
    "seller_address": "Plot 14, MIDC Bhosari, Pune 411026",
    "seller_state": "Maharashtra",
    "seller_state_code": "27",
    "seller_phone": "+91 20 2712 4455",
    "seller_email": "accounts@demomfg.example",
}
BUYERS = {
    "tata": ("Tata Motors Ltd", gst("27", "AAACT2727Q"), "Pimpri, Pune 411018", "Maharashtra", "27"),
    "maruti": (
        "Maruti Suzuki India Ltd",
        gst("06", "AAACM1234A"),
        "Palam Gurgaon Road, Gurugram 122015",
        "Haryana",
        "06",
    ),
    "ashok": ("Ashok Leyland Ltd", gst("33", "AAACA4567F"), "Ennore, Chennai 600057", "Tamil Nadu", "33"),
    "bajaj": ("Bajaj Auto Ltd", gst("27", "AAACB2345D"), "Akurdi, Pune 411035", "Maharashtra", "27"),
    "hero": ("Hero MotoCorp Ltd", gst("07", "AAACH3456E"), "Vasant Kunj, New Delhi 110070", "Delhi", "07"),
    "mahindra_dup": (
        "Mahindra & Mahindra Ltd",
        gst("27", "AAACM9999Z"),
        "Kandivali, Mumbai 400067",
        "Maharashtra",
        "27",
    ),
    "kaveri": (
        "Kaveri Auto Components Pvt Ltd",
        gst("29", "AAHCK4521M"),
        "Peenya, Bengaluru 560058",
        "Karnataka",
        "29",
    ),
}

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]  # fmt: skip
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def words(paise: int) -> str:
    r, p = divmod(paise, 100)
    parts = []
    for div, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand"), (100, "Hundred")):
        if r >= div:
            parts.append(f"{_two(r // div) if div != 100 else _ONES[r // div]} {name}")
            r %= div
    if r:
        parts.append(_two(r))
    s = "Rupees " + " ".join(parts)
    if p:
        s += f" and {_two(p)} Paise"
    return s + " Only"


def rs(paise: int) -> str:
    r = Decimal(paise) / 100
    whole = int(r)
    s = str(abs(whole))
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups + [tail])
    return ("-" if paise < 0 else "") + f"{s}.{abs(paise) % 100:02d}"


def p(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Sheet:
    """Draws text and remembers where each field was printed."""

    def __init__(self, n_pages: int) -> None:
        self.pages = [Image.new("RGB", (W, H), "white") for _ in range(n_pages)]
        self.cells: dict[str, Any] = {}
        self.font = ImageFont.load_default(size=19)
        self.bold = ImageFont.load_default(size=22)
        self.big = ImageFont.load_default(size=34)

    def text(self, page: int, xy: tuple[int, int], s: str, key: str | None = None, *, font: Any = None,
             conf: float = 0.97, store: dict[str, Any] | None = None, anchor: str = "la") -> None:  # fmt: skip
        d = ImageDraw.Draw(self.pages[page - 1])
        f = font or self.font
        d.text(xy, s, fill=(20, 20, 20), font=f, anchor=anchor)
        if key:
            x0, y0, x1, y1 = d.textbbox(xy, s, font=f, anchor=anchor)
            (store if store is not None else self.cells)[key] = {
                "raw": s, "confidence": conf, "page": page,
                "bbox": [round(x0 / W, 4), round(y0 / H, 4), round(x1 / W, 4), round(y1 / H, 4)],
            }  # fmt: skip

    def label_value(
        self, page: int, x: int, y: int, label: str, value: str | None, key: str, conf: float = 0.97
    ) -> None:
        if value is None:
            return
        self.text(page, (x, y), f"{label}:", font=self.font)
        self.text(page, (x + 200, y), value, key, conf=conf)

    def line(self, page: int, y: int) -> None:
        ImageDraw.Draw(self.pages[page - 1]).line([(60, y), (W - 60, y)], fill=(120, 120, 120), width=2)


def build(name: str, *, buyer: str, items: list[tuple[str, str, str, int, str, int, int]], inv_no: str,
          inv_date: date, intra: bool, extras: dict[str, str] | None = None, lines_per_page: int = 14,
          tamper: dict[str, Any] | None = None, minimal: bool = False, qr: bool = False,
          confidence: float = 0.97, photo: bool = False, paid_paise: int = 0) -> None:  # fmt: skip
    """items: (product, hsn, qty, unit_price_paise, uom, discount_paise, gst_rate)."""
    extras = extras or {}
    tamper = tamper or {}
    n_pages = max(1, -(-len(items) // lines_per_page))
    sh = Sheet(n_pages)
    bname, bgst, baddr, bstate, bcode = BUYERS[buyer]
    rng = random.Random(name)
    conf = lambda: round(max(0.55, min(0.99, confidence + rng.uniform(-0.06, 0.03))), 2)  # noqa: E731

    # header
    sh.text(
        1, (60, 50), "TAX INVOICE" if not minimal else "CASH BILL", "invoice_type", font=sh.big, conf=conf()
    )
    if not minimal:
        sh.text(1, (60, 100), SELLER["seller_name"], "seller_name", font=sh.bold, conf=conf())
        sh.text(1, (60, 132), SELLER["seller_address"], "seller_address", conf=conf())
        sh.text(1, (60, 158), "State:", font=sh.font)
        sh.text(1, (130, 158), SELLER["seller_state"], "seller_state", conf=conf())
        sh.text(1, (320, 158), "Code:", font=sh.font)
        sh.text(1, (385, 158), SELLER["seller_state_code"], "seller_state_code", conf=conf())
        sh.label_value(1, 60, 184, "GSTIN", SELLER["seller_gstin"], "seller_gstin", conf())
        sh.label_value(1, 60, 210, "Phone", SELLER["seller_phone"], "seller_phone", conf())
        sh.label_value(1, 60, 236, "Email", SELLER["seller_email"], "seller_email", conf())
    else:
        sh.text(1, (60, 100), "Shree Ganesh Engineering Works", "seller_name", font=sh.bold, conf=conf())
    sh.label_value(1, 700, 100, "Invoice No", inv_no, "invoice_number", conf())
    sh.label_value(1, 700, 126, "Invoice Date", inv_date.strftime("%d/%m/%Y"), "invoice_date", conf())
    for i, (k, label) in enumerate(
        [("due_date", "Due Date"), ("irn", "IRN"), ("ack_no", "Ack No"), ("ack_date", "Ack Date")]
    ):
        if k in extras:
            val = extras[k] if k != "irn" else extras[k][:28] + "…"
            sh.text(1, (700, 152 + i * 26), f"{label}:")
            sh.text(1, (900, 152 + i * 26), val, k, conf=conf())
            if k == "irn":
                sh.cells["irn"]["raw"] = extras["irn"]
    sh.line(1, 270)

    # buyer
    sh.text(1, (60, 285), "Bill To:", font=sh.bold)
    sh.text(1, (60, 315), bname, "buyer_name", font=sh.bold, conf=conf())
    if not minimal:
        sh.text(1, (60, 345), baddr, "buyer_billing_address", conf=conf())
        sh.label_value(1, 60, 371, "GSTIN", bgst, "buyer_gstin", conf())
        sh.text(1, (60, 397), "State:")
        sh.text(1, (130, 397), bstate, "buyer_state", conf=conf())
        sh.text(1, (320, 397), "Code:")
        sh.text(1, (385, 397), bcode, "buyer_state_code", conf=conf())
        sh.text(1, (700, 285), "Ship To:", font=sh.bold)
        sh.text(1, (700, 315), extras.get("ship_to", baddr), "buyer_shipping_address", conf=conf())
        sh.label_value(1, 700, 345, "Place of Supply", f"{bcode}-{bstate}", "place_of_supply", conf())
        sh.label_value(1, 700, 371, "Reverse Charge", "No", "reverse_charge", conf())
        if "contact" in extras:
            sh.label_value(1, 700, 397, "Contact", extras["contact"], "buyer_contact_person", conf())
    sh.line(1, 430)

    # items
    cols = [60, 100, 460, 560, 680, 750, 880, 960, 1080]
    heads = ["#", "Product", "HSN", "Qty", "Unit", "Rate", "GST%", "Tax", "Amount"]
    lines_out: list[dict[str, Any]] = []
    tot = dict(qty=Decimal(0), disc=0, taxable=0, cgst=0, sgst=0, igst=0)
    for idx, (prod, hsn, qty, price, uom, disc, rate) in enumerate(items):
        page = idx // lines_per_page + 1
        y0 = 445 if page == 1 else 80
        row = idx % lines_per_page
        if row == 0:
            for x, h in zip(cols, heads, strict=True):
                sh.text(page, (x, y0), h, font=sh.bold)
        y = y0 + 34 + row * 30
        q = Decimal(qty)
        taxable = p(q * price) - disc
        taxable = tamper.get("line_taxable", {}).get(idx, taxable)
        tax = p(Decimal(taxable) * rate / 100)
        half = p(Decimal(taxable) * rate / 200)
        cg, sg, ig = (half, half, 0) if intra else (0, 0, tax)
        total = taxable + cg + sg + ig
        cell: dict[str, Any] = {}
        sh.text(page, (cols[0], y), str(idx + 1))
        sh.text(page, (cols[1], y), prod, "product_name", store=cell, conf=conf())
        if not minimal:
            sh.text(page, (cols[2], y), hsn, "hsn", store=cell, conf=conf())
        sh.text(page, (cols[3], y), f"{q:,}", "quantity", store=cell, conf=conf())
        sh.text(page, (cols[4], y), uom, "uom", store=cell, conf=conf())
        sh.text(page, (cols[5], y), rs(price), "unit_price", store=cell, conf=conf())
        if not minimal:
            sh.text(page, (cols[6], y), f"{rate}%", "gst_rate", store=cell, conf=conf())
            sh.text(
                page, (cols[7], y), rs(cg + sg + ig), "igst" if not intra else "cgst", store=cell, conf=conf()
            )
            if intra:  # print CGST/SGST split under the tax column
                cell["cgst"]["raw"] = rs(cg)
                cell["sgst"] = dict(cell["cgst"], raw=rs(sg))
        sh.text(page, (cols[8], y), rs(total if not minimal else taxable), "total", store=cell, conf=conf())
        if not minimal:
            cell["taxable_value"] = dict(cell["total"], raw=rs(taxable), confidence=round(conf() - 0.05, 2))
            if disc:
                cell["discount_amount"] = dict(cell["unit_price"], raw=rs(disc))
        lines_out.append(cell)
        tot["qty"] += q
        tot["disc"] += disc
        tot["taxable"] += taxable
        tot["cgst"] += cg
        tot["sgst"] += sg
        tot["igst"] += ig

    # totals on the last page
    lp = n_pages
    ylast = (445 if lp == 1 else 80) + 34 + (((len(items) - 1) % lines_per_page) + 1) * 30 + 20
    sh.line(lp, ylast)
    freight = int(extras.get("freight", 0))
    gross = tot["taxable"] + tot["cgst"] + tot["sgst"] + tot["igst"] + freight
    grand = p(Decimal(gross) / 100) * 100  # round to rupee
    round_off = tamper.get("round_off", grand - gross)
    grand = tamper.get("grand_total", grand)
    y = ylast + 16
    rows: list[tuple[str, str, str]] = []
    if not minimal:
        rows += [
            ("Total Quantity", f"{tot['qty']:,}", "total_quantity"),
            ("Taxable Amount", rs(tot["taxable"]), "total_taxable"),
        ]
        if tot["disc"]:
            rows.append(("Discount", rs(tot["disc"]), "total_discount"))
        if intra:
            rows += [("CGST", rs(tot["cgst"]), "total_cgst"), ("SGST", rs(tot["sgst"]), "total_sgst")]
        else:
            rows.append(("IGST", rs(tot["igst"]), "total_igst"))
        if freight:
            rows.append(("Freight", rs(freight), "freight"))
        rows.append(("Round Off", rs(round_off), "round_off"))
    rows.append(("GRAND TOTAL", rs(grand), "grand_total"))
    for label, val, key in rows:
        sh.text(lp, (760, y), label, font=sh.bold if key == "grand_total" else sh.font)
        sh.text(
            lp,
            (1180, y),
            val,
            key,
            conf=conf(),
            anchor="ra",
            font=sh.bold if key == "grand_total" else sh.font,
        )
        y += 30
    if not minimal:
        sh.text(lp, (60, y + 10), words(tamper.get("words_paise", grand)), "amount_in_words", conf=conf())
        y += 50
        sh.label_value(lp, 60, y, "Payment Terms", extras.get("terms", "30 days"), "payment_terms", conf())
        sh.label_value(lp, 60, y + 26, "Bank", "HDFC Bank, Bhosari", "bank_name", conf())
        sh.label_value(lp, 60, y + 52, "A/c No", "50200012344417", "bank_account_number", conf())
        sh.label_value(lp, 60, y + 78, "IFSC", "HDFC0001234", "bank_ifsc", conf())
        if paid_paise:
            sh.label_value(lp, 700, y, "Amount Paid", rs(paid_paise), "amount_paid", conf())
            sh.label_value(lp, 700, y + 26, "Balance Due", rs(grand - paid_paise), "balance_due", conf())
        y += 120
        for key, label in (("transporter_name", "Transporter"), ("transporter_id", "Transporter ID"),
                           ("vehicle_number", "Vehicle No"), ("lr_number", "LR No"), ("eway_bill_number", "E-Way Bill"),
                           ("eway_bill_date", "E-Way Date"), ("dispatch_date", "Dispatch Date"),
                           ("transport_mode", "Mode"), ("place_of_dispatch", "Dispatch From"),
                           ("place_of_delivery", "Deliver To")):  # fmt: skip
            if key in extras:
                sh.label_value(lp, 60, y, label, extras[key], key, conf())
                y += 26
        y += 20
        sh.text(lp, (60, y), "Declaration: We declare that this invoice shows the actual price of the goods described.",
                "declaration", conf=conf())  # fmt: skip
        sh.text(lp, (820, y + 70), "For Demo Manufacturing Co.")
        sh.text(lp, (820, y + 130), "Authorised Signatory", "authorised_signatory", conf=conf())
    if qr:
        payload = {"SellerGstin": SELLER["seller_gstin"], "BuyerGstin": bgst, "DocNo": inv_no, "DocTyp": "INV",
                   "DocDt": inv_date.strftime("%d/%m/%Y"), "TotInvVal": float(Decimal(grand) / 100),
                   "ItemCnt": len(items), "MainHsnCode": items[0][1], "Irn": extras["irn"],
                   "IrnDt": f"{inv_date.isoformat()} 10:20:00"}  # fmt: skip
        enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")  # noqa: E731
        token = f"{enc({'alg': 'RS256', 'typ': 'JWT'})}.{enc({'data': json.dumps(payload), 'iss': 'NIC'})}.{enc('sig')}"
        buf = io.BytesIO()
        segno.make(token, error="m").save(buf, kind="png", scale=2, border=2)
        qr_img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
        sh.pages[lp - 1].paste(qr_img, (60, ylast + 16))  # empty space left of the totals

    # every field present; absent ones null (the model must never invent them)
    fields = {
        f.key: sh.cells.get(f.key, {"raw": None, "confidence": 0, "page": None, "bbox": None}) for f in FIELDS
    }
    lines = [{f.key: ln.get(f.key, {"raw": None, "confidence": 0, "page": None, "bbox": None}) for f in LINE_FIELDS}
             for ln in lines_out]  # fmt: skip
    (FIXTURES / f"{name}.json").write_text(
        json.dumps({"is_invoice": True, "fields": fields, "lines": lines}, indent=1)
    )

    pages = sh.pages
    if photo:
        pages = [
            pg.rotate(1.2, expand=True, fillcolor=(205, 198, 186)).filter(ImageFilter.GaussianBlur(0.6))
            for pg in pages
        ]
        tint = Image.new("RGB", pages[0].size, (238, 232, 220))
        pages = [Image.blend(pg, tint, 0.18) for pg in pages]
        pages[0].save(SAMPLES / f"{name}.jpg", "JPEG", quality=82)
    else:
        pages[0].save(SAMPLES / f"{name}.pdf", "PDF", save_all=True, append_images=pages[1:], resolution=150)
    print(f"{name}: {len(items)} lines, {n_pages} page(s), grand total {rs(grand)}")


BOLT = ("M10 hex bolts", "7318", "50000", 100_00 // 10, "PCS", 0, 18)


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    d = date(2026, 11, 2)
    build("clean_pdf", buyer="tata", inv_no="DMC/26-27/0412", inv_date=d, intra=True,
          extras={"due_date": "02/12/2026", "contact": "R. Kulkarni"},
          items=[("M8 nylock nuts", "7318", "120000", 1_50, "PCS", 0, 18),
                 ("M10 hex bolts", "7318", "20000", 10_00, "PCS", 20_000_00, 18)])  # fmt: skip
    build("phone_photo", buyer="maruti", inv_no="DMC/26-27/0398", inv_date=date(2026, 10, 27), intra=False,
          photo=True, confidence=0.86, items=[("M10 hex bolts", "7318", "50000", 10_00, "PCS", 0, 18)])  # fmt: skip
    many = [
        (f"Fastener kit {chr(65 + i)}", "7318", str(1000 * (i + 1)), 2_00 + i * 25, "PCS", 0, 18)
        for i in range(18)
    ]
    build("multi_page", buyer="mahindra_dup", inv_no="DMC/26-27/0420", inv_date=date(2026, 11, 5), intra=True,
          items=many, lines_per_page=12)  # fmt: skip
    build("igst", buyer="ashok", inv_no="DMC/26-27/0388", inv_date=date(2026, 10, 18), intra=False,
          extras={"due_date": "17/11/2026"}, paid_paise=5_00_000_00,
          items=[("U-bolts", "7318", "8000", 145_00, "PCS", 0, 18)])  # fmt: skip
    build("einvoice_qr", buyer="bajaj", inv_no="DMC/26-27/0431", inv_date=date(2026, 11, 9), intra=True, qr=True,
          extras={"irn": "a3f9c1e47b2d8e6f0a1b3c5d7e9f1a2b4c6d8e0f2a4b6c8d0e2f4a6b8c0d2e4f",
                  "ack_no": "112610098765432", "ack_date": "09/11/2026"},
          items=[("Wheel studs", "7318", "40000", 55_00, "PCS", 0, 18)])  # fmt: skip
    build("eway_transport", buyer="hero", inv_no="DMC/26-27/0425", inv_date=date(2026, 11, 7), intra=False,
          extras={"freight": "12500_00".replace("_", ""), "transporter_name": "VRL Logistics Ltd",
                  "transporter_id": gst("29", "AABCV3609C"), "vehicle_number": "MH12AB4567", "lr_number": "LR-778812",
                  "eway_bill_number": "331009876543", "eway_bill_date": "07/11/2026", "dispatch_date": "07/11/2026",
                  "transport_mode": "Road", "place_of_dispatch": "Pune", "place_of_delivery": "New Delhi"},
          items=[("M6 socket screws", "7318", "60000", 16_50, "PCS", 0, 18)])  # fmt: skip
    build("bad_totals", buyer="kaveri", inv_no="DMC/26-27/0433", inv_date=date(2026, 11, 10), intra=False,
          tamper={"line_taxable": {1: 3_10_000_00}, "grand_total": 9_99_999_00, "round_off": 3_00},
          items=[("M12 flange bolts", "7318", "10000", 18_00, "PCS", 0, 18),
                 ("Spring washers", "7318", "200000", 1_50, "PCS", 0, 18)])  # fmt: skip
    build("minimal", buyer="kaveri", inv_no="152", inv_date=date(2026, 9, 14), intra=True, minimal=True, photo=True,
          confidence=0.78, items=[("MS nuts M16", "", "500", 12_00, "PCS", 0, 0)])  # fmt: skip
    # The "minimal" cash bill is from a small buyer with no GSTIN; drop buyer details the bill doesn't show.
    fx = json.loads((FIXTURES / "minimal.json").read_text())
    fx["fields"]["buyer_name"]["raw"] = "Shree Ganesh Engineering Works"
    fx["fields"]["seller_name"] = {"raw": None, "confidence": 0, "page": None, "bbox": None}
    (FIXTURES / "minimal.json").write_text(json.dumps(fx, indent=1))
    (FIXTURES / "default.json").write_text((FIXTURES / "clean_pdf.json").read_text())
    (FIXTURES / "not_invoice.json").write_text(json.dumps({"is_invoice": False, "fields": {}, "lines": []}))


if __name__ == "__main__":
    main()

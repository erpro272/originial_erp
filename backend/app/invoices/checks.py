"""Deterministic invoice checks. Errors block saving; warnings need acknowledging.

Each check has a stable id (`code:path`) so the user's acknowledgements can be matched.
Money tolerance is ₹1 (100 paise) to allow for per-line rounding.
"""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from app.core.gst import gstin_errors, pan_from_gstin, state_code_from_gstin, words_to_paise
from app.invoices.normalize import dec, lv, v

TOL = 100  # paise
Severity = Literal["error", "warning"]


@dataclass
class Check:
    code: str
    severity: Severity
    path: str  # "fields.grand_total" or "lines.0.taxable_value"
    message: str

    @property
    def id(self) -> str:
        return f"{self.code}:{self.path}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"id": self.id}


def _rs(paise: int) -> str:
    sign = "−" if paise < 0 else ""
    r = Decimal(abs(paise)) / 100
    whole = int(r)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    frac = (r - whole).quantize(Decimal("0.01"))
    return f"{sign}₹{s}" + (f".{str(frac)[2:]}" if frac else "")


def _p(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def run_checks(doc: dict[str, Any], today: date) -> list[Check]:
    out: list[Check] = []

    def add(code: str, sev: Severity, path: str, msg: str) -> None:
        out.append(Check(code, sev, path, msg))

    # --- needed to save into the ERP -----------------------------------------------------
    for key, label in (("invoice_number", "Invoice number"), ("invoice_date", "Invoice date"),
                       ("buyer_name", "Customer name"), ("grand_total", "Grand total")):  # fmt: skip
        if v(doc, key) is None:
            raw = doc["fields"][key]["raw"]
            msg = (
                f"{label} is required to save."
                if raw is None
                else f"{label} '{raw}' can't be read as a valid value."
            )
            add("required", "error", f"fields.{key}", msg)

    # --- lines -----------------------------------------------------------------------------
    sums = {k: 0 for k in ("discount_amount", "taxable_value", "cgst", "sgst", "igst", "cess")}
    qty_sum = Decimal(0)
    have = {k: False for k in sums} | {"quantity": False}
    for i, ln in enumerate(doc["lines"]):
        p = f"lines.{i}"
        qty, price = dec(lv(ln, "quantity")), lv(ln, "unit_price")
        disc_amt, disc_pct, taxable = (
            lv(ln, "discount_amount"),
            dec(lv(ln, "discount_pct")),
            lv(ln, "taxable_value"),
        )
        rate = dec(lv(ln, "gst_rate"))
        if qty is not None:
            qty_sum += qty
            have["quantity"] = True
        for k in sums:
            if lv(ln, k) is not None:
                sums[k] += lv(ln, k)
                have[k] = True
        if qty is not None and price is not None and taxable is not None:
            gross = qty * price
            discount = (
                disc_amt
                if disc_amt is not None
                else (_p(gross * disc_pct / 100) if disc_pct is not None else 0)
            )
            expected = _p(gross) - discount
            if abs(expected - taxable) > TOL:
                add("line_taxable", "warning", f"{p}.taxable_value",
                    f"Line {i + 1}: qty × price − discount = {_rs(expected)}, but taxable value is {_rs(taxable)}.")  # fmt: skip
        if taxable is not None and rate is not None:
            igst, cgst, sgst = lv(ln, "igst"), lv(ln, "cgst"), lv(ln, "sgst")
            if igst:
                exp = _p(Decimal(taxable) * rate / 100)
                if abs(exp - igst) > TOL:
                    add("line_tax", "warning", f"{p}.igst",
                        f"Line {i + 1}: IGST at {rate}% should be {_rs(exp)}, invoice shows {_rs(igst)}.")  # fmt: skip
            for k, amt in (("cgst", cgst), ("sgst", sgst)):
                if amt is not None:
                    exp = _p(Decimal(taxable) * rate / 200)
                    if abs(exp - amt) > TOL:
                        add("line_tax", "warning", f"{p}.{k}",
                            f"Line {i + 1}: {k.upper()} at {rate / 2}% should be {_rs(exp)}, invoice shows {_rs(amt)}.")  # fmt: skip
        total = lv(ln, "total")
        if taxable is not None and total is not None:
            exp = taxable + sum(lv(ln, k) or 0 for k in ("cgst", "sgst", "igst", "cess"))
            if abs(exp - total) > TOL:
                add("line_total", "warning", f"{p}.total",
                    f"Line {i + 1}: taxable + taxes = {_rs(exp)}, but the line total is {_rs(total)}.")  # fmt: skip

    # --- totals vs lines -------------------------------------------------------------------
    if doc["lines"]:
        for line_key, total_key, label in (
            ("discount_amount", "total_discount", "Total discount"), ("taxable_value", "total_taxable", "Total taxable"),
            ("cgst", "total_cgst", "Total CGST"), ("sgst", "total_sgst", "Total SGST"),
            ("igst", "total_igst", "Total IGST"), ("cess", "total_cess", "Total cess"),
        ):  # fmt: skip
            total = v(doc, total_key)
            if total is not None and have[line_key] and abs(total - sums[line_key]) > TOL:
                add("sum_mismatch", "warning", f"fields.{total_key}",
                    f"{label} is {_rs(total)} but the lines add up to {_rs(sums[line_key])}.")  # fmt: skip
        tq = dec(v(doc, "total_quantity"))
        if tq is not None and have["quantity"] and tq != qty_sum:
            add("sum_mismatch", "warning", "fields.total_quantity",
                f"Total quantity is {tq} but the lines add up to {qty_sum}.")  # fmt: skip

    # --- grand total, round-off, words ---------------------------------------------------
    gt = v(doc, "grand_total")
    taxable_total = (
        v(doc, "total_taxable")
        if v(doc, "total_taxable") is not None
        else (sums["taxable_value"] if have["taxable_value"] else None)
    )
    if gt is not None and taxable_total is not None:
        parts = [taxable_total] + [
            v(doc, k) if v(doc, k) is not None else (sums[lk] if lk and have[lk] else 0)
            for k, lk in (("total_cgst", "cgst"), ("total_sgst", "sgst"), ("total_igst", "igst"), ("total_cess", "cess"),
                          ("freight", None), ("packing", None), ("other_charges", None))
        ]  # fmt: skip
        expected = sum(parts) + (v(doc, "round_off") or 0)
        if abs(expected - gt) > TOL:
            add("grand_total", "warning", "fields.grand_total",
                f"Taxable + taxes + charges ± round-off = {_rs(expected)}, but the grand total is {_rs(gt)}.")  # fmt: skip
    ro = v(doc, "round_off")
    if ro is not None and abs(ro) >= 100:
        add("round_off", "warning", "fields.round_off", f"Round-off is {_rs(ro)}; it should be under ₹1.")
    words = doc["fields"]["amount_in_words"]["raw"]
    if words and gt is not None:
        parsed = words_to_paise(words)
        if parsed is None:
            add("words", "warning", "fields.amount_in_words", "Amount in words couldn't be read as a number.")
        elif abs(parsed - gt) >= 100 or (parsed % 100 and parsed != gt):
            add("words", "warning", "fields.amount_in_words",
                f"Amount in words says {_rs(parsed)}, the grand total is {_rs(gt)}.")  # fmt: skip

    # --- GSTIN / PAN / state ---------------------------------------------------------------
    for party in ("seller", "buyer"):
        g = v(doc, f"{party}_gstin")
        if g is None:
            continue
        errs = gstin_errors(g)
        if errs:
            add("gstin", "error", f"fields.{party}_gstin", f"{party.title()} GSTIN: {errs[0]}")
            continue
        pan = v(doc, f"{party}_pan")
        if pan and pan != pan_from_gstin(g):
            add("pan_gstin", "warning", f"fields.{party}_pan",
                f"{party.title()} PAN {pan} doesn't match the PAN inside the GSTIN ({pan_from_gstin(g)}).")  # fmt: skip
        for key in (f"{party}_state_code", f"{party}_state"):
            st = v(doc, key)
            if st and st != state_code_from_gstin(g):
                add("state_gstin", "warning", f"fields.{key}",
                    f"{party.title()} state ({st}) doesn't match the GSTIN state code ({state_code_from_gstin(g)}).")  # fmt: skip
                break
    t = v(doc, "transporter_id")
    if t and len(t.replace(" ", "")) == 15 and (errs := gstin_errors(t.replace(" ", "").upper())):
        add("gstin", "error", "fields.transporter_id", f"Transporter GSTIN: {errs[0]}")

    # --- intra vs inter-state supply --------------------------------------------------------
    seller_state = v(doc, "seller_state_code") or v(doc, "seller_state") or (
        state_code_from_gstin(v(doc, "seller_gstin")) if v(doc, "seller_gstin") and not gstin_errors(v(doc, "seller_gstin")) else None)  # fmt: skip
    pos = v(doc, "place_of_supply") or v(doc, "buyer_state_code") or v(doc, "buyer_state")
    cg = (v(doc, "total_cgst") or sums["cgst"]) or 0
    sg = (v(doc, "total_sgst") or sums["sgst"]) or 0
    ig = (v(doc, "total_igst") or sums["igst"]) or 0
    if seller_state and pos and (cg or sg or ig):
        if seller_state == pos and ig:
            add("supply_type", "warning", "fields.total_igst",
                "Seller and place of supply are in the same state, so CGST + SGST should apply, not IGST.")  # fmt: skip
        elif seller_state != pos and (cg or sg):
            add("supply_type", "warning", "fields.total_cgst",
                "Seller and place of supply are in different states, so IGST should apply, not CGST + SGST.")  # fmt: skip

    # --- payment ---------------------------------------------------------------------------
    bal = v(doc, "balance_due")
    if bal is not None and gt is not None:
        exp = gt - (v(doc, "amount_paid") or 0) - (v(doc, "advance_received") or 0)
        if abs(exp - bal) > TOL:
            add("balance", "warning", "fields.balance_due",
                f"Grand total − paid − advance = {_rs(exp)}, but balance due is {_rs(bal)}.")  # fmt: skip

    # --- dates -----------------------------------------------------------------------------
    inv_date = date.fromisoformat(v(doc, "invoice_date")) if v(doc, "invoice_date") else None
    if inv_date:
        if inv_date > today + timedelta(days=1):
            add("date_future", "warning", "fields.invoice_date", "Invoice date is in the future.")
        for key, label in (("due_date", "Due date"), ("delivery_date", "Delivery date"),
                           ("dispatch_date", "Dispatch date")):  # fmt: skip
            d = v(doc, key)
            if d and date.fromisoformat(d) < inv_date:
                add("date_order", "warning", f"fields.{key}", f"{label} is before the invoice date.")
    for key in ("invoice_date", "due_date", "ack_date", "eway_bill_date", "dispatch_date", "delivery_date"):
        cell = doc["fields"][key]
        if cell["raw"] and cell["value"] is None and key != "invoice_date":
            add("date_unreadable", "warning", f"fields.{key}", f"'{cell['raw']}' isn't a valid date.")

    # --- QR cross-check ----------------------------------------------------------------------
    qr = doc.get("qr")
    if qr and qr.get("kind") == "gst_einvoice":
        pairs = [("seller_gstin", "seller_gstin", "Seller GSTIN"), ("buyer_gstin", "buyer_gstin", "Buyer GSTIN"),
                 ("doc_no", "invoice_number", "Invoice number"), ("irn", "irn", "IRN")]  # fmt: skip
        for qk, fk, label in pairs:
            if qr.get(qk) and v(doc, fk) and str(qr[qk]).strip().upper() != str(v(doc, fk)).strip().upper():
                add(
                    "qr_mismatch",
                    "warning",
                    f"fields.{fk}",
                    f"{label} on the invoice doesn't match the QR code ({qr[qk]}).",
                )
        if qr.get("doc_date") and v(doc, "invoice_date") and qr["doc_date"] != v(doc, "invoice_date"):
            add(
                "qr_mismatch",
                "warning",
                "fields.invoice_date",
                f"Invoice date doesn't match the QR code ({qr['doc_date']}).",
            )
        if (
            qr.get("total_value_paise") is not None
            and gt is not None
            and abs(qr["total_value_paise"] - gt) > TOL
        ):
            add("qr_mismatch", "warning", "fields.grand_total",
                f"Grand total doesn't match the QR code ({_rs(qr['total_value_paise'])}).")  # fmt: skip
    return out


def blocking(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.severity == "error"]


def unacknowledged(checks: list[Check], acknowledged: set[str]) -> list[Check]:
    return [c for c in checks if c.severity == "warning" and c.id not in acknowledged]

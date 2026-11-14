"""Trial layout template (Maruti Suzuki purchase order) read with Tesseract, no AI."""

from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from app.invoices import templates
from app.invoices.checks import run_checks
from app.invoices.normalize import build_document

SAMPLE = Path(__file__).parents[2] / "samples" / "templates" / "maruti_po_trial.png"
pytestmark = pytest.mark.skipif(not templates.available(), reason="tesseract not installed")


@pytest.mark.parametrize("scale", [1.0, 0.75, 1.5])
def test_reads_the_trial_po_at_any_size(scale: float) -> None:
    im = Image.open(SAMPLE)
    im = im.resize((round(im.width * scale), round(im.height * scale)))
    tpl, out = templates.extract([im]) or (None, {})
    assert tpl is templates.MARUTI_PO
    f = {k: v["raw"] for k, v in out["fields"].items()}
    assert f["invoice_number"] == "MSIL/PO/26-002347"
    assert f["invoice_date"] == "08 Jan 2026"
    assert f["seller_gstin"] == "06AABCA4456K1Z8"
    assert f["seller_pan"] == "AABCA4456K"
    assert f["seller_email"] == "rakesh.gupta@apexauto.in"
    assert f["subtotal"] == "27,00,000.00"
    assert f["grand_total"] == "31,86,000.00"
    lines = [{k: v["raw"] for k, v in ln.items()} for ln in out["lines"]]
    assert [ln["sku"] for ln in lines] == ["72111M55R00", "72410M55R00", "74100M55R10"]
    assert [ln["total"] for ln in lines] == ["12,50,000.00", "8,90,000.00", "5,60,000.00"]
    assert lines[0]["product_name"] == "Front Bumper Reinforcement (Hatchback)"


def test_purchase_order_cannot_be_saved_as_invoice() -> None:
    _, out = templates.extract([Image.open(SAMPLE)]) or (None, {})
    doc = build_document(out, None)
    assert any(c.code == "not_invoice" and c.severity == "error" for c in run_checks(doc, date(2026, 11, 14)))


def test_other_documents_do_not_match() -> None:
    assert templates.extract([Image.new("RGB", (800, 1000), "white")]) is None


@pytest.mark.parametrize(("raw", "fmt", "out"), [
    ("O7AAACM0824R1ZV", "gstin", "07AAACM0824R1ZV"),
    ("GSTIN: O6AABCA4456K1Z8", "gstin", "06AABCA4456K1Z8"),
    ("₹ 27,00,000.00", "money", "27,00,000.00"),
    ("1,000 _", "number", "1,000"),
    ("72111MS5R00", "99999A99A99", "72111M55R00"),
    ("too short", "99999A99A99", "too short"),
])  # fmt: skip
def test_clean(raw: str, fmt: str, out: str) -> None:
    assert templates.clean(raw, fmt) == out

from datetime import date

import pytest

from app.invoices.fields import ai_schema
from app.invoices.normalize import apply_edits, build_document, normalize, overall_confidence, parse_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("13/11/2026", date(2026, 11, 13)), ("03-04-26", date(2026, 4, 3)), ("03.04.2026", date(2026, 4, 3)),
     ("2026-11-13", date(2026, 11, 13)), ("13-Nov-2026", date(2026, 11, 13)), ("13 November 2026", date(2026, 11, 13)),
     ("1st Dec, 2026", date(2026, 12, 1)), ("Nov 13 2026", date(2026, 11, 13)), ("31/02/2026", None), ("soon", None)],
)  # fmt: skip
def test_dates_are_day_first(raw: str, expected: date | None) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("ftype", "raw", "value"),
    [("money", "₹ 1,18,000.00", 11800000), ("number", "1,20,000 PCS", "120000"), ("percent", "18%", "18"),
     ("gstin", "27 aapfu 0939f1zv", "27AAPFU0939F1ZV"), ("state", "Maharashtra", "27"), ("state_code", "27", "27"),
     ("bool", "Not Applicable", False), ("bool", "Yes", True), ("bool", "maybe", None),
     ("phone", "+91 98100-12345", "9810012345"), ("invoice_type", "TAX INVOICE (Original for Recipient)", "tax_invoice"),
     ("invoice_type", "Credit Note", "credit_note"), ("text", "  M10   hex bolts ", "M10 hex bolts"),
     ("money", None, None), ("text", "   ", None)],
)  # fmt: skip
def test_normalize(ftype, raw, value) -> None:  # type: ignore[no-untyped-def]
    assert normalize(ftype, raw) == value


def test_build_document_keeps_raw_and_never_fills_gaps() -> None:
    doc = build_document({"fields": {"invoice_number": {"raw": "INV/26-27/0042", "confidence": 0.98, "page": 1,
                                                        "bbox": [0.1, 0.1, 0.3, 0.12]},
                                     "due_date": {"raw": None, "confidence": 0.9, "page": 1, "bbox": [0, 0, 1, 1]}},
                          "lines": [{"quantity": {"raw": "50,000", "confidence": 0.9, "page": 1, "bbox": None}}]},
                         qr=None)  # fmt: skip
    assert doc["fields"]["invoice_number"]["raw"] == "INV/26-27/0042"
    assert doc["fields"]["invoice_number"]["value"] == "INV/26-27/0042"
    # Missing fields are present, null, with no confidence or box (nothing invented).
    assert doc["fields"]["due_date"] == {
        "raw": None,
        "value": None,
        "confidence": None,
        "page": 1,
        "bbox": None,
        "edited": False,
    }
    assert doc["fields"]["grand_total"]["value"] is None
    assert len(doc["fields"]) == 72 and doc["lines"][0]["quantity"]["value"] == "50000"
    assert doc["lines"][0]["unit_price"]["raw"] is None


def test_edits_and_confidence() -> None:
    doc = build_document({"fields": {"grand_total": {"raw": "1,000.00", "confidence": 0.5, "page": 1, "bbox": None},
                                     "invoice_number": {"raw": "A1", "confidence": 0.9, "page": 1, "bbox": None}},
                          "lines": []}, None)  # fmt: skip
    assert overall_confidence(doc) == 0.7
    edited = apply_edits(doc, {"grand_total": "1,100.00", "invoice_number": "A1"}, None)
    assert edited["fields"]["grand_total"] | {} == {"raw": "1,100.00", "value": 110000, "confidence": 1.0, "page": 1,
                                                    "bbox": None, "edited": True}  # fmt: skip
    assert edited["fields"]["invoice_number"]["edited"] is False  # unchanged
    assert doc["fields"]["grand_total"]["raw"] == "1,000.00"  # original untouched


def test_schema_is_strict() -> None:
    s = ai_schema()
    assert s["additionalProperties"] is False
    assert len(s["properties"]["fields"]["required"]) == 72
    assert s["$defs"]["field"]["properties"]["raw"]["type"] == ["string", "null"]

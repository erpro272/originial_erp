"""Turns the model's raw strings into typed values. Deterministic, no AI.

Extraction document (stored in extraction_runs.data):
    {"is_invoice": bool,
     "fields": {key: {"raw", "value", "confidence", "page", "bbox", "edited"}},
     "lines": [{key: {...same...}}],
     "qr": {...} | None}
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.gst import normalize_state, parse_decimal, parse_money_paise
from app.invoices.fields import FIELD_BY_KEY, FIELDS, LINE_FIELD_BY_KEY, LINE_FIELDS, FieldType

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}  # fmt: skip


def parse_date(raw: str | None) -> date | None:
    """Indian invoices are day-first: 03/04/2026 is 3 April 2026."""
    if not raw:
        return None
    s = raw.strip().lower().replace(",", " ")
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    try:
        if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s):
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(y, int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{1,2})[\s\-/.]*([a-z]{3})[a-z]*[\s\-/.]*(\d{2,4})", s):
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(y, _MONTHS[m[2]], int(m[1]))
        if m := re.fullmatch(r"([a-z]{3})[a-z]*\s+(\d{1,2})\s+(\d{4})", s):
            return date(int(m[3]), _MONTHS[m[1]], int(m[2]))
    except (ValueError, KeyError):
        return None
    return None


_TRUE = {"yes", "y", "true", "applicable", "present", "signed", "digitally signed"}
_FALSE = {"no", "n", "false", "not applicable", "na", "n/a", "nil", "absent", "not present"}

_INVOICE_TYPES = [
    ("credit note", "credit_note"), ("debit note", "debit_note"), ("bill of supply", "bill_of_supply"),
    ("proforma", "proforma"), ("export", "export_invoice"), ("delivery challan", "delivery_challan"),
    ("tax invoice", "tax_invoice"), ("invoice", "tax_invoice"),
]  # fmt: skip


def normalize(ftype: FieldType, raw: str | None) -> Any:
    if raw is None or not str(raw).strip():
        return None
    r = str(raw).strip()
    match ftype:
        case "date":
            d = parse_date(r)
            return d.isoformat() if d else None
        case "money":
            return parse_money_paise(r)
        case "number" | "percent":
            v = parse_decimal(r)
            return str(v) if v is not None else None
        case "gstin" | "pan":
            return re.sub(r"[\s\-]", "", r).upper()
        case "state" | "state_code":
            return normalize_state(r)
        case "bool":
            low = r.lower()
            return True if low in _TRUE else False if low in _FALSE else None
        case "phone":
            digits = re.sub(r"\D", "", r)
            return digits[-10:] if len(digits) >= 10 else digits or None
        case "email":
            return r.lower()
        case "invoice_type":
            low = r.lower()
            return next((code for text, code in _INVOICE_TYPES if text in low), "other")
        case _:
            return re.sub(r"\s+", " ", r)


def _cell(spec_type: FieldType, src: dict[str, Any] | str | float | None) -> dict[str, Any]:
    if isinstance(src, str | int | float) and not isinstance(
        src, bool
    ):  # compact item cell: just the printed text
        src = {"raw": str(src)}
    src = src if isinstance(src, dict) else {}
    raw = src.get("raw")
    raw = None if raw is None or str(raw).strip() == "" else str(raw)
    conf = src.get("confidence")
    bbox = src.get("bbox")
    return {
        "raw": raw,
        "value": normalize(spec_type, raw),
        "confidence": max(0.0, min(1.0, float(conf)))
        if isinstance(conf, int | float) and raw is not None
        else None,
        "page": src.get("page") if isinstance(src.get("page"), int) else None,
        "bbox": bbox if isinstance(bbox, list) and len(bbox) == 4 and raw is not None else None,
        "edited": False,
    }


def build_document(ai: dict[str, Any], qr: dict[str, Any] | None) -> dict[str, Any]:
    """From model output to a full document: every field present, raw kept, value normalised."""
    fields_in = ai.get("fields") or {}
    lines_in = ai.get("lines") or []
    return {
        "is_invoice": bool(ai.get("is_invoice", True)),
        "document_kind": ai.get("document_kind", "invoice"),
        "fields": {f.key: _cell(f.type, fields_in.get(f.key)) for f in FIELDS},
        "lines": [{f.key: _cell(f.type, (ln or {}).get(f.key)) for f in LINE_FIELDS} for ln in lines_in],
        "qr": qr,
    }


def apply_edits(
    doc: dict[str, Any], fields: dict[str, str | None], lines: list[dict[str, str | None]] | None
) -> dict[str, Any]:
    """User corrections (raw text). Edited cells get confidence 1 and keep their page/bbox."""
    out = {**doc, "fields": dict(doc["fields"])}
    for key, raw in fields.items():
        spec = FIELD_BY_KEY.get(key)
        if spec is None:
            continue
        old = doc["fields"].get(key) or _cell(spec.type, None)
        if (old.get("raw") or None) != (raw or None):
            out["fields"][key] = {**old, "raw": raw or None, "value": normalize(spec.type, raw),
                                  "confidence": 1.0 if raw else None, "edited": True}  # fmt: skip
    if lines is not None:
        new_lines = []
        for i, ln in enumerate(lines):
            prev = doc["lines"][i] if i < len(doc["lines"]) else {}
            row = {}
            for f in LINE_FIELDS:
                old = prev.get(f.key) or _cell(f.type, None)
                raw = ln.get(f.key)
                if (old.get("raw") or None) != (raw or None):
                    row[f.key] = {**old, "raw": raw or None, "value": normalize(f.type, raw),
                                  "confidence": 1.0 if raw else None, "edited": True}  # fmt: skip
                else:
                    row[f.key] = old
            new_lines.append(row)
        out["lines"] = new_lines
    return out


def overall_confidence(doc: dict[str, Any]) -> float | None:
    vals = [c["confidence"] for c in doc["fields"].values() if c.get("confidence") is not None]
    vals += [c["confidence"] for ln in doc["lines"] for c in ln.values() if c.get("confidence") is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def v(doc: dict[str, Any], key: str) -> Any:
    cell = doc["fields"].get(key)
    return cell.get("value") if cell else None


def lv(line: dict[str, Any], key: str) -> Any:
    cell = line.get(key)
    return cell.get("value") if cell else None


def dec(x: Any) -> Decimal | None:
    return Decimal(str(x)) if x is not None else None


__all__ = [
    "LINE_FIELD_BY_KEY",
    "apply_edits",
    "build_document",
    "normalize",
    "overall_confidence",
    "parse_date",
]

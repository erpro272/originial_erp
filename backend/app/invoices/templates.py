"""Layout templates: read a known document layout with OCR (Tesseract), no AI.

A template is "trained" on one sample page: it names the words that identify the layout,
two anchor words used to line a new scan up with the sample (scale + shift), and the
box on the sample where each field sits. Each box is OCR'd on its own and the text is
cleaned with a per-field format (e.g. GSTIN digit/letter positions).

shortcut: templates live in code and only one trial template exists; per-company templates
stored in the DB (with a "teach a new layout" screen) come if the trial works out.
"""

import io
import itertools
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps, ImageStat

log = logging.getLogger(__name__)

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in sample pixels


@dataclass(frozen=True)
class Zone:
    box: Box
    kind: str = "line"  # line | block (lines joined with ", ") | wrap (one text wrapped over lines)
    fmt: str | None = None  # gstin | pan | money | number | mask like "99999A99A99"
    chars: str | None = None  # restrict OCR to these characters


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    size: tuple[int, int]  # sample page size in pixels
    signature: tuple[str, ...]  # words that must all be on the page (upper case)
    anchors: tuple[tuple[str, Box], tuple[str, Box]]  # two words far apart, with their sample boxes
    fields: dict[str, Zone]
    document_kind: str = "invoice"
    # Line table: one row per amount found in the `row_marker` column (x0, x1) of `table`.
    table: Box | None = None
    row_marker: tuple[float, float] | None = None
    columns: dict[str, Zone] = field(default_factory=dict)


# Trial: the Maruti Suzuki purchase order the owner supplied (sample is 1199 x 1312 px).
MARUTI_PO = Template(
    id="maruti-po-trial",
    name="Maruti Suzuki purchase order (trial)",
    size=(1199, 1312),
    signature=("PURCHASE", "MARUTI", "SUZUKI"),
    anchors=(("PURCHASE", (813, 28, 1014, 58)), ("HSN", (47, 1164, 84, 1179))),
    document_kind="purchase_order",
    fields={
        "invoice_number": Zone((905, 86, 1160, 116)),  # PO No.
        "invoice_date": Zone((905, 120, 1160, 148)),  # PO Date
        "buyer_name": Zone((46, 82, 470, 114)),
        "buyer_billing_address": Zone((46, 118, 470, 168), "block"),
        "buyer_gstin": Zone((110, 192, 300, 217), fmt="gstin"),
        "buyer_shipping_address": Zone((640, 310, 1160, 380), "block"),
        "buyer_phone": Zone((705, 403, 900, 429)),
        "seller_name": Zone((52, 283, 600, 314)),
        "seller_address": Zone((52, 311, 600, 358), "block"),
        "seller_gstin": Zone((116, 354, 300, 379), fmt="gstin"),
        "seller_pan": Zone((100, 375, 300, 399), fmt="pan"),
        "seller_phone": Zone((116, 418, 300, 442)),
        "seller_email": Zone((112, 439, 420, 466)),
        "payment_terms": Zone((60, 517, 272, 562), "wrap"),
        "transport_mode": Zone((578, 517, 765, 545)),
        "delivery_terms": Zone((820, 517, 968, 545)),
        "total_quantity": Zone((212, 792, 395, 823)),
        "subtotal": Zone((975, 789, 1170, 816), fmt="money"),
        "grand_total": Zone((975, 856, 1172, 886), fmt="money"),
        "authorised_signatory": Zone((650, 1224, 820, 1253)),
    },
    table=(18, 645, 1181, 782),
    row_marker=(1018, 1180),  # Total Amount column
    columns={
        "sku": Zone((92, 0, 252, 0), fmt="99999A99A99", chars="0123456789ABCDEFGHJKLMNPRSTUVWXYZ"),
        "product_name": Zone((256, 0, 530, 0), "wrap"),
        "description": Zone((535, 0, 740, 0)),  # drawing / spec. no.
        "quantity": Zone((744, 0, 872, 0), fmt="number"),
        "unit_price": Zone((878, 0, 1013, 0), fmt="money"),
        "total": Zone((1018, 0, 1180, 0), fmt="money"),
    },
)

TEMPLATES: tuple[Template, ...] = (MARUTI_PO,)


# ---- OCR -----------------------------------------------------------------------------------


@dataclass
class Word:
    text: str
    conf: float
    box: Box


def available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr(img: Image.Image, psm: int, chars: str | None = None) -> list[Word]:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    extra = ["-c", f"tessedit_char_whitelist={chars}"] if chars else []
    exe = shutil.which("tesseract") or "tesseract"
    out = subprocess.run(  # noqa: S603 - fixed arguments; the image goes in on stdin
        [exe, "stdin", "stdout", "--psm", str(psm), "-l", "eng", *extra, "tsv"],
        input=buf.getvalue(), capture_output=True, check=True, timeout=60,
    )  # fmt: skip
    words = []
    for row in out.stdout.decode("utf-8", "replace").splitlines()[1:]:
        c = row.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) >= 0:
            x, y, w, h = (int(v) for v in c[6:10])
            words.append(Word(c[11].strip(), float(c[10]) / 100, (x, y, x + w, y + h)))
    return words


def ocr_text(pages: list[Image.Image]) -> str:
    """Every OCR line with its page and box (0..1 of the page), for the text model: `p1 [x0,y0,x1,y1] text`."""
    out: list[str] = []
    exe = shutil.which("tesseract") or "tesseract"
    for n, img in enumerate(pages, start=1):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        res = subprocess.run(  # noqa: S603 - fixed arguments; the image goes in on stdin
            [exe, "stdin", "stdout", "--psm", "3", "-l", "eng", "tsv"], input=buf.getvalue(), capture_output=True,
            check=True, timeout=90,
        )  # fmt: skip
        w, h = img.size
        lines: dict[tuple[str, ...], list[list[str]]] = {}
        for row in res.stdout.decode("utf-8", "replace").splitlines()[1:]:
            c = row.split("\t")
            if len(c) == 12 and c[11].strip() and float(c[10]) >= 0:
                lines.setdefault(tuple(c[2:5]), []).append(c)
        for words in lines.values():
            x0 = min(int(c[6]) for c in words) / w
            y0 = min(int(c[7]) for c in words) / h
            x1 = max(int(c[6]) + int(c[8]) for c in words) / w
            y1 = max(int(c[7]) + int(c[9]) for c in words) / h
            text = " ".join(c[11].strip() for c in words)
            out.append(f"p{n} [{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}] {text}")
    return "\n".join(out)


@dataclass
class _Fit:
    """Maps sample coordinates to the scanned page (independent scale + shift per axis)."""

    sx: float
    sy: float
    dx: float
    dy: float

    def box(self, b: Box) -> Box:
        return (b[0] * self.sx + self.dx, b[1] * self.sy + self.dy,
                b[2] * self.sx + self.dx, b[3] * self.sy + self.dy)  # fmt: skip


def _find(words: list[Word], text: str, near: tuple[float, float] = (0, 0)) -> Word | None:
    """The word (exact, ignoring case/punctuation) closest to where the sample has it."""
    hits = [w for w in words if re.sub(r"[^A-Z]", "", w.text.upper()) == text]
    return min(hits, key=lambda w: abs(w.box[0] - near[0]) + abs(w.box[1] - near[1])) if hits else None


def _fit(t: Template, words: list[Word], width: int) -> _Fit | None:
    if not all(_find(words, s) for s in t.signature):
        return None
    k = width / t.size[0]  # rough scale, only to pick the right copy of a repeated word
    (a_txt, a_ref), (b_txt, b_ref) = t.anchors
    a = _find(words, a_txt, (a_ref[0] * k, a_ref[1] * k))
    b = _find(words, b_txt, (b_ref[0] * k, b_ref[1] * k))
    if a is None or b is None:
        return None
    sx = (b.box[0] - a.box[0]) / (b_ref[0] - a_ref[0])
    sy = (b.box[1] - a.box[1]) / (b_ref[1] - a_ref[1])
    if not (0.25 < sx < 4 and 0.25 < sy < 4):
        return None
    return _Fit(sx, sy, a.box[0] - a_ref[0] * sx, a.box[1] - a_ref[1] * sy)


def _read_zone(page: Image.Image, box: Box, zone: Zone) -> tuple[str | None, float]:
    kind = zone.kind
    x0, y0, x1, y1 = (max(0, round(v)) for v in box)
    crop = page.crop((x0, y0, min(x1, page.width), min(y1, page.height))).convert("L")
    if crop.width < 4 or crop.height < 4:
        return None, 0.0
    if ImageStat.Stat(crop).mean[0] < 128:  # light text on a dark band
        crop = ImageOps.invert(crop)
    scale = max(1.0, 64 / crop.height) if kind == "line" else 2.0
    crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)
    crop = ImageOps.expand(crop, 12, fill=255)
    words = _ocr(crop, 7 if kind == "line" else 6, zone.chars)
    if not words:
        return None, 0.0
    lines: dict[float, list[Word]] = {}
    for w in words:  # group into lines by vertical position
        key = next((k for k in lines if abs(k - w.box[1]) < 12 * scale), w.box[1])
        lines.setdefault(key, []).append(w)
    sep = " " if kind == "wrap" else ", "
    text = sep.join(" ".join(w.text for w in ws) for _, ws in sorted(lines.items()))
    text = re.sub(r"\s*,\s*,\s*|,\s*,", ", ", text).strip(" |[]{}")
    return text or None, sum(w.conf for w in words) / len(words)


# ---- per-field clean-up --------------------------------------------------------------------

_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                           "S": "5", "B": "8", "Z": "2", "G": "6"})  # fmt: skip
_TO_LETTER = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})


def _mask(raw: str, mask: str) -> str | None:
    """Fix OCR letter/digit swaps where the format says which one belongs ('9' digit, 'A' letter)."""
    s = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
    if len(s) != len(mask):
        return None
    return "".join(
        c.translate(_TO_DIGIT) if m == "9" else c.translate(_TO_LETTER) if m == "A" else c
        for c, m in zip(s, mask, strict=True)
    )


def clean(raw: str | None, fmt: str | None) -> str | None:
    if raw is None or fmt is None:
        return raw
    if fmt == "gstin":
        tail = raw.split(":")[-1]
        return _mask(tail, "99AAAAA9999AXAX") or raw
    if fmt == "pan":
        return _mask(raw.split(":")[-1], "AAAAA9999A") or raw
    if fmt in ("money", "number"):
        m = re.search(r"\d[\d,]*\.\d{2}" if fmt == "money" else r"\d[\d,]*(?:\.\d+)?", raw.replace(" ", ""))
        return m.group(0) if m else raw
    return _mask(raw, fmt) or raw


# ---- extraction ----------------------------------------------------------------------------


def _cell(page: Image.Image, fit: _Fit, zone: Zone, box: Box | None = None) -> dict[str, Any]:
    b = fit.box(box or zone.box)
    raw, conf = _read_zone(page, b, zone)
    raw = clean(raw, zone.fmt)
    bbox = [
        round(max(0.0, min(1.0, v / d)), 4) for v, d in zip(b, (page.width, page.height) * 2, strict=True)
    ]
    return {"raw": raw, "confidence": round(conf, 2) if raw else 0, "page": 1 if raw else None,
            "bbox": bbox if raw else None}  # fmt: skip


def _rows(t: Template, page: Image.Image, fit: _Fit) -> list[tuple[float, float]]:
    """Row bands (sample y): one per amount printed in the marker column."""
    assert t.table and t.row_marker
    top, bottom = t.table[1], t.table[3]
    x0, y0, x1, y1 = (round(v) for v in fit.box((t.row_marker[0], top, t.row_marker[1], bottom)))
    crop = page.crop((x0, y0, x1, y1)).convert("L")
    k = 2.0
    crop = ImageOps.expand(crop.resize((round(crop.width * k), round(crop.height * k))), 12, fill=255)
    marks = sorted(
        ((w.box[1] + w.box[3]) / 2 - 12) / k / fit.sy + top
        for w in _ocr(crop, 6)
        if re.search(r"\d[\d,]*\.\d{2}", w.text)
    )
    edges = [top] + [(a + b) / 2 for a, b in itertools.pairwise(marks)] + [bottom]
    return list(itertools.pairwise(edges)) if marks else []


def extract(pages: list[Image.Image]) -> tuple[Template, dict[str, Any]] | None:
    """Model-shaped output ({is_invoice, document_kind, fields, lines}) if a template fits page 1."""
    if not pages or not available():
        return None
    page = pages[0].convert("RGB")
    k = 2000 / page.width  # small text OCRs badly; read the whole page at a fixed width
    words = _ocr(page.resize((2000, round(page.height * k)), Image.Resampling.LANCZOS), 11)
    for w in words:
        w.box = tuple(v / k for v in w.box)  # type: ignore[assignment]
    for t in TEMPLATES:
        fit = _fit(t, words, page.width)
        if fit is None:
            continue
        log.info("invoice matched layout template %s", t.id)
        fields = {key: _cell(page, fit, z) for key, z in t.fields.items()}
        lines = [
            {key: _cell(page, fit, z, (z.box[0], y0, z.box[2], y1)) for key, z in t.columns.items()}
            for y0, y1 in (_rows(t, page, fit) if t.table else [])
        ]
        return t, {"is_invoice": True, "document_kind": t.document_kind, "fields": fields, "lines": lines}
    return None

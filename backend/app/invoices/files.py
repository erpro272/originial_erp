"""File handling for invoice uploads: type detection, page images, AI input, QR decoding.

The QR code is decoded here, in code, never by the AI. A GST e-invoice QR is a signed JWT
from the IRP; we decode its payload (seller/buyer GSTIN, number, date, value, IRN) and
cross-check it against the extracted fields. Signature verification against the NIC public
key is a follow-up (needs the IRP certificate).
"""

import base64
import io
import json
from dataclasses import dataclass
from typing import Any

import pypdfium2 as pdfium
import zxingcpp
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.core.gst import parse_money_paise
from app.invoices.normalize import parse_date

register_heif_opener()

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 20
PAGE_LONG_EDGE = 2000  # viewer + QR
AI_LONG_EDGE = 2400


class UnsupportedFile(ValueError):
    pass


@dataclass(frozen=True)
class Detected:
    doc_format: str  # image | pdf
    content_type: str  # what we will store / send
    ext: str


def detect(data: bytes) -> Detected:
    """By content, not by the name or the browser's claimed type."""
    if len(data) > MAX_BYTES:
        raise UnsupportedFile("File is larger than 20 MB.")
    head = data[:16]
    if head.startswith(b"%PDF"):
        return Detected("pdf", "application/pdf", "pdf")
    if head.startswith(b"\xff\xd8\xff"):
        return Detected("image", "image/jpeg", "jpg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detected("image", "image/png", "png")
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return Detected("image", "image/heic", "heic")
    raise UnsupportedFile("Only JPG, PNG, HEIC and PDF files are supported.")


def _fit(img: Image.Image, long_edge: int) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > long_edge:
        img.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    return img


def page_images(data: bytes, det: Detected) -> list[Image.Image]:
    if det.doc_format == "pdf":
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise UnsupportedFile("This PDF can't be opened (damaged or password-protected).") from exc
        if len(pdf) > MAX_PAGES:
            raise UnsupportedFile(f"PDF has {len(pdf)} pages; the limit is {MAX_PAGES}.")
        pages = [_fit(pdf[i].render(scale=2).to_pil(), PAGE_LONG_EDGE) for i in range(len(pdf))]
        pdf.close()
        return pages
    try:
        return [_fit(Image.open(io.BytesIO(data)), PAGE_LONG_EDGE)]
    except Exception as exc:
        raise UnsupportedFile("This image can't be opened.") from exc


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def ai_image(data: bytes) -> bytes:
    """JPEG for the model (HEIC isn't accepted by the API; large photos are shrunk)."""
    img = _fit(Image.open(io.BytesIO(data)), AI_LONG_EDGE)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ---- QR -------------------------------------------------------------------------------------


def _b64url_json(part: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def parse_qr_text(text: str) -> dict[str, Any]:
    """Decode a QR payload. GST e-invoice QRs are signed JWTs whose payload holds `data`."""
    payload: Any = None
    parts = text.strip().split(".")
    if len(parts) == 3:
        try:
            payload = _b64url_json(parts[1])
            if isinstance(payload.get("data"), str):
                payload = json.loads(payload["data"])
            elif isinstance(payload.get("data"), dict):
                payload = payload["data"]
        except (ValueError, AttributeError):
            payload = None
    if payload is None:
        try:
            payload = json.loads(text)
        except ValueError:
            return {"kind": "other", "text": text[:2000]}
    if not isinstance(payload, dict) or not ({"SellerGstin", "Irn"} & payload.keys()):
        return {"kind": "other", "text": text[:2000]}
    d = parse_date(str(payload.get("DocDt", "")))
    total = payload.get("TotInvVal")
    return {
        "kind": "gst_einvoice",
        "signed": len(parts) == 3,
        "signature_verified": False,
        "seller_gstin": payload.get("SellerGstin"),
        "buyer_gstin": payload.get("BuyerGstin"),
        "doc_no": payload.get("DocNo"),
        "doc_type": payload.get("DocTyp"),
        "doc_date": d.isoformat() if d else None,
        "total_value_paise": parse_money_paise(str(total)) if total is not None else None,
        "item_count": payload.get("ItemCnt"),
        "main_hsn": payload.get("MainHsnCode"),
        "irn": payload.get("Irn"),
        "irn_date": payload.get("IrnDt"),
    }


def decode_qr(pages: list[Image.Image]) -> dict[str, Any] | None:
    for i, img in enumerate(pages, start=1):
        for r in zxingcpp.read_barcodes(img):
            if r.format == zxingcpp.BarcodeFormat.QRCode and r.text:
                return parse_qr_text(r.text) | {"page": i}
    return None

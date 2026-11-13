import base64
import io
import json

import pytest
import segno
from PIL import Image

from app.invoices.files import UnsupportedFile, decode_qr, detect, page_images, parse_qr_text

EINV = {"SellerGstin": "27AAPFU0939F1ZV", "BuyerGstin": "29AAGCB7383J1Z4", "DocNo": "INV/26-27/0042",
        "DocTyp": "INV", "DocDt": "13/11/2026", "TotInvVal": 118000.5, "ItemCnt": 1,
        "MainHsnCode": "7318", "Irn": "a" * 64, "IrnDt": "2026-11-13 10:20:00"}  # fmt: skip


def jwt(payload: dict) -> str:  # type: ignore[type-arg]
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'RS256', 'typ': 'JWT'})}.{enc({'data': json.dumps(payload), 'iss': 'NIC'})}.c2lnbmF0dXJl"


def qr_image(text: str) -> Image.Image:
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=6, border=4)
    canvas = Image.new("RGB", (1200, 1600), "white")
    canvas.paste(Image.open(io.BytesIO(buf.getvalue())), (450, 100))  # top-right, fully inside
    return canvas


def test_decode_signed_einvoice_qr() -> None:
    qr = decode_qr([Image.new("RGB", (800, 1000), "white"), qr_image(jwt(EINV))])
    assert qr is not None
    assert qr["kind"] == "gst_einvoice" and qr["signed"] is True and qr["page"] == 2
    assert qr["seller_gstin"] == "27AAPFU0939F1ZV" and qr["doc_date"] == "2026-11-13"
    assert qr["total_value_paise"] == 11800050 and qr["irn"] == "a" * 64


def test_other_qr_and_no_qr() -> None:
    assert parse_qr_text("upi://pay?pa=abc@okhdfc") == {"kind": "other", "text": "upi://pay?pa=abc@okhdfc"}
    assert decode_qr([Image.new("RGB", (400, 400), "white")]) is None


@pytest.mark.parametrize(
    ("head", "fmt"),
    [(b"%PDF-1.7\n", "pdf"), (b"\xff\xd8\xff\xe0", "image"), (b"\x89PNG\r\n\x1a\n", "image"),
     (b"\x00\x00\x00\x18ftypheic", "image")],
)  # fmt: skip
def test_detect_by_content(head: bytes, fmt: str) -> None:
    assert detect(head + b"\x00" * 32).doc_format == fmt


@pytest.mark.parametrize("data", [b"MZ\x90\x00 not an image", b"<html>", b"PK\x03\x04 docx"])
def test_detect_rejects_other_files(data: bytes) -> None:
    with pytest.raises(UnsupportedFile):
        detect(data)


def test_size_limit() -> None:
    with pytest.raises(UnsupportedFile, match="20 MB"):
        detect(b"%PDF" + b"0" * (20 * 1024 * 1024))


def test_pdf_pages_rendered() -> None:
    imgs = [Image.new("RGB", (595, 842), c) for c in ("white", "lightgray")]
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:])
    pages = page_images(buf.getvalue(), detect(buf.getvalue()))
    assert len(pages) == 2 and max(pages[0].size) <= 2000


def test_heic_supported() -> None:
    from pillow_heif import from_pillow

    buf = io.BytesIO()
    from_pillow(Image.new("RGB", (300, 400), "white")).save(buf, quality=50)
    data = buf.getvalue()
    assert detect(data).content_type == "image/heic"
    assert page_images(data, detect(data))[0].size == (300, 400)

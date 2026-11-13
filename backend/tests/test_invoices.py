"""Upload -> extract (mock AI, real files, real QR) -> review -> match -> save."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.filetokens import make as make_token
from app.invoices.models import ExtractionRun, Invoice, InvoiceLine, InvoicePayment, InvoiceTransport
from tests import factories as f
from tests.conftest import TODAY, Company, headers_for, make_company

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "invoices"
TATA = f.gstin("27", "AAACT2727Q")
MARUTI = f.gstin("06", "AAACM1234A")
MAHINDRA = f.gstin("27", "AAACM5678C")


@pytest.fixture(scope="module")
async def client_mod(app, tenants):  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api") as c:
        yield c


@pytest.fixture(scope="module")
async def co() -> Company:
    c = await make_company("inv")
    await f.customer(c.id, "Tata Motors", gst=TATA, tier="key")
    await f.customer(c.id, "Maruti Suzuki", gst=MARUTI)
    await f.customer(c.id, "Mahindra", gst=MAHINDRA)
    pid = await f.product(c.id, "M8-NYL", "M8 nylock nuts")
    async with tenant_session(c.id) as s:
        from app.orders.models import Order

        tata = (await s.execute(text("SELECT id FROM customers WHERE name = 'Tata Motors'"))).scalar_one()
        s.add(Order(number="ORD-1041", customer_id=tata, product_id=pid, quantity=Decimal(120000), unit="pcs",
                    unit_price_paise=150, sales_paise=18_000_000, cost_paise=15_000_000, processing_days=5,
                    ship_date=TODAY, priority="high", status="in_production"))  # fmt: skip
    return c


async def upload(
    client: AsyncClient, h: dict[str, str], *names: str, raw: list[tuple[str, bytes]] | None = None
) -> dict:  # type: ignore[type-arg]
    files = [("files", (n, (SAMPLES / n).read_bytes())) for n in names] + [("files", r) for r in raw or []]
    r = await client.post("/invoices/uploads", headers=h, files=files)
    assert r.status_code == 201, r.text
    return r.json()


async def detail(client: AsyncClient, h: dict[str, str], uid: str) -> dict:  # type: ignore[type-arg]
    r = await client.get(f"/invoices/uploads/{uid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def raw(doc: dict, key: str) -> str | None:  # type: ignore[type-arg]
    return doc["fields"][key]["raw"]


async def test_clean_pdf_full_flow(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    batch = await upload(client_mod, h, "clean_pdf.pdf")
    uid = batch["uploads"][0]["id"]
    d = await detail(client_mod, h, uid)
    assert d["upload"]["status"] == "needs_review" and d["upload"]["ai_mode"] == "mock"
    assert d["upload"]["page_count"] == 1 and 0.8 < d["upload"]["overall_confidence"] <= 1
    assert raw(d["document"], "invoice_number") == "DMC/26-27/0412"
    assert d["document"]["fields"]["invoice_date"]["value"] == "2026-11-02"
    assert d["document"]["fields"]["grand_total"]["value"] == 42_480_000
    assert d["document"]["fields"]["invoice_number"]["bbox"] is not None
    assert d["checks"] == []
    assert d["match"]["kind"] == "existing" and d["match"]["candidates"][0]["name"] == "Tata Motors"
    # page image served through a short-lived signed link
    page = await client_mod.get(d["pages"][0]["url"].removeprefix("/api"))
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"

    r = await client_mod.post(f"/invoices/uploads/{uid}/save", headers=h, json={
        "customer": {"mode": "existing", "customer_id": d["match"]["customer_id"]}})  # fmt: skip
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["customer_action"] == "existing" and out["order_number"] == "ORD-1041"

    async with tenant_session(co.id) as s:
        inv = await s.get(Invoice, uuid.UUID(out["invoice_id"]))
        assert inv is not None and inv.grand_total_paise == 42_480_000 and inv.supply_type == "intra"
        assert inv.financial_year == "2026-27" and inv.balance_due_paise == 42_480_000
        lines = (await s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id))).scalars().all()
        assert [ln.quantity for ln in lines] == [Decimal(120000), Decimal(20000)]
        pay = (
            await s.execute(select(InvoicePayment).where(InvoicePayment.invoice_id == inv.id))
        ).scalar_one()
        assert pay.bank_account_last4 == "4417" and b"50200012344417" not in (pay.bank_account_enc or b"")
        runs = (await s.execute(select(ExtractionRun).where(ExtractionRun.upload_id == uuid.UUID(uid))
                                .order_by(ExtractionRun.version))).scalars().all()  # fmt: skip
        assert [r.source for r in runs] == ["model", "user"]
        assert "50200012344417" not in json.dumps([r.data for r in runs]) + "".join(
            r.raw_output or "" for r in runs
        )
        event = (
            await s.execute(text("SELECT payload FROM outbox_events WHERE type = 'invoice.created'"))
        ).scalar_one()
        assert event["invoice_id"] == out["invoice_id"]
    # customer sales history and receivables reflect the invoice
    cust = (await client_mod.get("/customers", headers=h, params={"q": "tata"})).json()["items"][0]
    assert cust["outstanding_paise"] == 42_480_000 and cust["invoices"] == 1
    # saved invoices can't be saved again; the same invoice again is an exact duplicate
    assert (await client_mod.post(f"/invoices/uploads/{uid}/save", headers=h, json={
        "customer": {"mode": "existing", "customer_id": d["match"]["customer_id"]}})).status_code == 400  # fmt: skip
    again = (await upload(client_mod, h, "clean_pdf.pdf"))["uploads"][0]["id"]
    d2 = await detail(client_mod, h, again)
    assert any(c["code"] == "duplicate" and c["severity"] == "error" for c in d2["checks"])
    r = await client_mod.post(f"/invoices/uploads/{again}/save", headers=h, json={
        "customer": {"mode": "existing", "customer_id": d["match"]["customer_id"]}})  # fmt: skip
    assert r.status_code == 400 and r.json()["error"]["details"]["checks"][0]["code"] == "duplicate"


async def test_phone_photo_and_igst(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    b = await upload(client_mod, h, "phone_photo.jpg", "igst.pdf")
    photo = await detail(client_mod, h, b["uploads"][0]["id"])
    igst = await detail(client_mod, h, b["uploads"][1]["id"])
    assert photo["upload"]["doc_format"] == "image" and photo["match"]["kind"] == "existing"
    assert photo["upload"]["overall_confidence"] < 0.9  # phone photo reads less confidently
    assert photo["checks"] == [] and igst["checks"] == []
    assert igst["document"]["fields"]["total_igst"]["value"] == 20_880_000
    assert igst["document"]["fields"]["total_cgst"]["value"] is None
    assert igst["match"]["kind"] == "new"  # Ashok Leyland isn't a customer in this company


async def test_multi_page_and_possible_duplicate_customer(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "multi_page.pdf"))["uploads"][0]["id"]
    d = await detail(client_mod, h, uid)
    assert d["upload"]["page_count"] == 2 and len(d["pages"]) == 2 and len(d["document"]["lines"]) == 18
    assert {ln["product_name"]["page"] for ln in d["document"]["lines"]} == {1, 2}
    assert d["document"]["fields"]["grand_total"]["page"] == 2
    m = d["match"]
    assert m["kind"] == "ambiguous" and m["candidates"][0]["name"] == "Mahindra"
    assert "Different GSTIN" in m["candidates"][0]["reasons"]
    # The user decides it's a different business: create it from the prefilled form.
    pre = m["prefill"]
    assert pre["name"] == "Mahindra & Mahindra Ltd" and pre["gstin"] == f.gstin("27", "AAACM9999Z")
    r = await client_mod.post(
        f"/invoices/uploads/{uid}/save", headers=h, json={"customer": {"mode": "new", "customer": pre}}
    )
    assert r.status_code == 200, r.text and r.json()["customer_action"] == "new"


async def test_einvoice_qr_decoded_and_cross_checked(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "einvoice_qr.pdf"))["uploads"][0]["id"]
    d = await detail(client_mod, h, uid)
    qr = d["document"]["qr"]
    assert (
        qr["kind"] == "gst_einvoice"
        and qr["doc_no"] == "DMC/26-27/0431"
        and qr["total_value_paise"] == 259_600_000
    )
    assert raw(d["document"], "irn") == qr["irn"] and d["checks"] == []
    # Editing the number away from the QR's value raises a cross-check warning.
    r = await client_mod.post(
        f"/invoices/uploads/{uid}/check", headers=h, json={"fields": {"invoice_number": "DMC/26-27/0999"}}
    )
    assert [(c["code"], c["path"]) for c in r.json()["checks"]] == [("qr_mismatch", "fields.invoice_number")]


async def test_eway_transport_saved(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "eway_transport.pdf"))["uploads"][0]["id"]
    d = await detail(client_mod, h, uid)
    assert d["checks"] == [] and raw(d["document"], "eway_bill_number") == "331009876543"
    r = await client_mod.post(
        f"/invoices/uploads/{uid}/save",
        headers=h,
        json={"customer": {"mode": "new", "customer": d["match"]["prefill"]}},
    )
    assert r.status_code == 200, r.text
    async with tenant_session(co.id) as s:
        tr = (
            await s.execute(
                select(InvoiceTransport).where(
                    InvoiceTransport.invoice_id == uuid.UUID(r.json()["invoice_id"])
                )
            )
        ).scalar_one()
        assert (tr.vehicle_no, tr.eway_bill_date.isoformat(), tr.mode) == ("MH12AB4567", "2026-11-07", "Road")  # type: ignore[union-attr]
        inv = await s.get(Invoice, uuid.UUID(r.json()["invoice_id"]))
        assert inv is not None and inv.freight_paise == 1_250_000 and inv.supply_type == "inter"


async def test_bad_totals_need_acknowledging(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "bad_totals.pdf"))["uploads"][0]["id"]
    d = await detail(client_mod, h, uid)
    codes = sorted(c["code"] for c in d["checks"])
    assert codes == ["grand_total", "line_taxable", "round_off"]
    assert all(c["severity"] == "warning" for c in d["checks"])
    body = {"customer": {"mode": "new", "customer": d["match"]["prefill"]}}
    r = await client_mod.post(f"/invoices/uploads/{uid}/save", headers=h, json=body)
    assert r.status_code == 400 and len(r.json()["error"]["details"]["checks"]) == 3
    r = await client_mod.post(
        f"/invoices/uploads/{uid}/save",
        headers=h,
        json=body | {"acknowledged": [c["id"] for c in d["checks"]]},
    )
    assert r.status_code == 200, r.text


async def test_minimal_invoice_keeps_nulls(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "minimal.jpg"))["uploads"][0]["id"]
    d = await detail(client_mod, h, uid)
    present = sorted(k for k, c in d["document"]["fields"].items() if c["raw"] is not None)
    assert present == ["buyer_name", "grand_total", "invoice_date", "invoice_number", "invoice_type"]
    assert all(
        c["value"] is None and c["confidence"] is None
        for k, c in d["document"]["fields"].items()
        if k not in present
    )
    assert d["checks"] == [] and d["match"]["kind"] == "new" and d["match"]["prefill"]["gstin"] is None


async def test_invalid_gstin_blocks_saving(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "igst.pdf"))["uploads"][0]["id"]
    bad = TATA[:-1] + ("A" if TATA[-1] != "A" else "B")
    r = await client_mod.post(
        f"/invoices/uploads/{uid}/check", headers=h, json={"fields": {"buyer_gstin": bad}}
    )
    assert {"code": "gstin", "severity": "error", "path": "fields.buyer_gstin"}.items() <= r.json()["checks"][
        0
    ].items()
    put = await client_mod.put(
        f"/invoices/uploads/{uid}/draft", headers=h, json={"fields": {"buyer_gstin": bad}, "verified": True}
    )
    assert put.status_code == 400
    put = await client_mod.put(
        f"/invoices/uploads/{uid}/draft",
        headers=h,
        json={"fields": {"payment_terms": "45 days"}, "verified": True},
    )
    assert put.json()["status"] == "verified"
    d = await detail(client_mod, h, uid)
    assert (
        raw(d["document"], "payment_terms") == "45 days"
        and d["document"]["fields"]["payment_terms"]["edited"] is True
    )
    assert d["versions"] == 2


async def test_possible_duplicate_needs_confirmation(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    first = (await upload(client_mod, h, "phone_photo.jpg"))["uploads"][0]["id"]
    d = await detail(client_mod, h, first)
    cid = d["match"]["customer_id"]
    assert (
        await client_mod.post(
            f"/invoices/uploads/{first}/save",
            headers=h,
            json={"customer": {"mode": "existing", "customer_id": cid}},
        )
    ).status_code == 200
    second = (await upload(client_mod, h, "phone_photo.jpg"))["uploads"][0]["id"]
    edit = {"fields": {"invoice_number": "DMC/26-27/0398-B"}}  # different number, same customer/date/total
    chk = (await client_mod.post(f"/invoices/uploads/{second}/check", headers=h, json=edit)).json()
    assert chk["duplicate"]["flag"] == "possible"
    body = edit | {"customer": {"mode": "existing", "customer_id": cid}}
    assert (
        await client_mod.post(f"/invoices/uploads/{second}/save", headers=h, json=body)
    ).status_code == 409
    r = await client_mod.post(
        f"/invoices/uploads/{second}/save", headers=h, json=body | {"confirm_possible_duplicate": True}
    )
    assert r.status_code == 200, r.text


async def test_rejected_and_failed_files(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    b = await upload(
        client_mod,
        h,
        raw=[("notes.txt", b"hello"), ("not_invoice.png", (SAMPLES / "minimal.jpg").read_bytes())],
    )
    assert b["rejected"] == [
        {"file_name": "notes.txt", "error": "Only JPG, PNG, HEIC and PDF files are supported."}
    ]
    d = await detail(client_mod, h, b["uploads"][0]["id"])
    assert d["upload"]["status"] == "failed" and "doesn't look like an invoice" in d["upload"]["error"]
    r = await client_mod.post(
        f"/invoices/uploads/{b['uploads'][0]['id']}/reject", headers=h, json={"reason": "Not an invoice"}
    )
    assert r.json()["status"] == "rejected"
    lst = (await client_mod.get("/invoices/uploads", headers=h)).json()
    assert lst["summary"]["imported"] >= 1 and "rejected" in lst["counts"]


async def test_roles_and_masking(client_mod: AsyncClient, co: Company) -> None:
    owner = await headers_for(client_mod, co)
    assert (
        await client_mod.get("/invoices/uploads", headers=await headers_for(client_mod, co, "planner"))
    ).status_code == 403
    assert (
        await client_mod.get("/invoices/uploads", headers=await headers_for(client_mod, co, "accountant"))
    ).status_code == 200
    uid = (await upload(client_mod, owner, "igst.pdf"))["uploads"][0]["id"]
    d = await detail(client_mod, owner, uid)
    assert raw(d["document"], "bank_account_number") == "50200012344417"  # owner sees it
    inv_id = (await client_mod.post("/invoices/uploads/" + uid + "/save", headers=owner,
              json={"customer": {"mode": "new", "customer": d["match"]["prefill"] | {"name": "Ashok Leyland Ltd 2", "gstin": None}},
                    "acknowledged": [c["id"] for c in d["checks"]], "confirm_possible_duplicate": True})).json()  # fmt: skip
    planner = await headers_for(client_mod, co, "planner")
    seen = (await client_mod.get(f"/invoices/{inv_id['invoice_id']}", headers=planner)).json()
    assert (
        seen["payment"]["bank_account"] == "XXXXXXXXXX4417" and seen["payment"]["sensitive_visible"] is False
    )
    full = (await client_mod.get(f"/invoices/{inv_id['invoice_id']}", headers=owner)).json()
    assert full["payment"]["bank_account"] == "50200012344417"


async def test_file_links_are_signed_and_tenant_bound(client_mod: AsyncClient, co: Company) -> None:
    other = await make_company("inv-other")
    good = make_token(co.id, f"{co.id}/invoices/x/page-1.png")
    assert (await client_mod.get(f"/files/{good[:-2]}xx")).status_code == 400  # tampered
    forged = make_token(other.id, f"{co.id}/invoices/x/page-1.png")  # key outside the token's tenant
    assert (await client_mod.get(f"/files/{forged}")).status_code == 400
    expired = make_token(co.id, f"{co.id}/invoices/x/page-1.png", ttl=-1)
    assert (await client_mod.get(f"/files/{expired}")).status_code == 400


async def test_stored_files_are_encrypted_with_company_key(client_mod: AsyncClient, co: Company) -> None:
    from app.core.storage import get_storage
    from app.invoices.models import InvoiceUpload

    h = await headers_for(client_mod, co)
    uid = (await upload(client_mod, h, "clean_pdf.pdf"))["uploads"][0]["id"]
    async with tenant_session(co.id) as s:
        u = await s.get(InvoiceUpload, uuid.UUID(uid))
        assert u is not None
    stored = await get_storage().get(u.file_key)
    assert not stored.startswith(b"%PDF") and b"DMC/26-27" not in stored  # the store only has ciphertext
    page = await get_storage().get(u.page_keys[0])
    assert not page.startswith(b"\x89PNG")
    d = await detail(client_mod, h, uid)
    original = await client_mod.get(d["original_url"].removeprefix("/api"))
    assert original.content.startswith(b"%PDF")  # decrypted only when served through a signed link

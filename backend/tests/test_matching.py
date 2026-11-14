import pytest
from httpx import ASGITransport, AsyncClient  # noqa: F401

from app.core.db import tenant_session
from app.invoices.matching import clean_name, match_customer
from app.invoices.normalize import build_document
from tests import factories as f
from tests.conftest import Company, make_company


def doc(**fields: str) -> dict:  # type: ignore[type-arg]
    return build_document({"fields": {k: {"raw": v, "confidence": 0.9, "page": 1, "bbox": None} for k, v in fields.items()},
                           "lines": []}, None)  # fmt: skip


@pytest.fixture(scope="module")
async def co() -> Company:
    c = await make_company("match")
    await f.customer(c.id, "Maruti Suzuki", gst=f.gstin("06", "AAACM1234A"))
    await f.customer(c.id, "Bajaj Auto", phone="+91 98100 22222")
    await f.customer(c.id, "Hero MotoCorp")
    await f.customer(c.id, "Hero Cycles")
    await f.customer(c.id, "Hosur Auto Components")
    return c


def test_clean_name() -> None:
    assert clean_name("M/s. Maruti Suzuki India Pvt. Ltd.") == "maruti suzuki"
    assert clean_name("Mahindra & Mahindra Limited") == "mahindra mahindra"


@pytest.mark.parametrize(
    ("fields", "kind", "who"),
    [
        (
            {"buyer_name": "MSIL", "buyer_gstin": f.gstin("06", "AAACM1234A")},
            "existing",
            "Maruti Suzuki",
        ),  # GSTIN wins
        ({"buyer_name": "Maruti Suzuki India Limited"}, "existing", "Maruti Suzuki"),  # fuzzy, no GSTIN
        ({"buyer_name": "B. A. L.", "buyer_phone": "9810022222"}, "existing", "Bajaj Auto"),  # phone
        (
            {"buyer_name": "Maruti Suzuki India Ltd", "buyer_gstin": f.gstin("07", "AAACM7777A")},
            "ambiguous",
            None,
        ),
        ({"buyer_name": "Hero"}, "ambiguous", None),  # two similar customers
        ({"buyer_name": "Kaveri Auto Components"}, "new", None),
        ({"buyer_name": "Kaveri Auto Components Pvt Ltd"}, "new", None),  # shares only generic words
    ],
)
async def test_match(co: Company, fields: dict, kind: str, who: str | None) -> None:  # type: ignore[type-arg]
    async with tenant_session(co.id) as s:
        m = await match_customer(s, doc(**fields))
    assert m.kind == kind
    if who:
        assert m.candidates[0].name == who and m.customer_id == m.candidates[0].customer_id
    else:
        assert m.customer_id is None

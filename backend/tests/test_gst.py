from datetime import date

import pytest

from app.core.gst import (
    financial_year,
    gstin_checksum,
    gstin_errors,
    is_valid_gstin,
    normalize_state,
    pan_errors,
    pan_from_gstin,
    parse_decimal,
    parse_money_paise,
    words_to_paise,
)


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    body = f"{state}{pan}{entity}Z"
    return body + gstin_checksum(body)


@pytest.mark.parametrize("gstin", ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4"])
def test_real_world_gstins_are_valid(gstin: str) -> None:
    assert gstin_errors(gstin) == []


def test_generated_gstin_valid_and_typo_detected() -> None:
    g = make_gstin("33", "AAACA4567F")
    assert is_valid_gstin(g)
    typo = g[:5] + ("B" if g[5] != "B" else "C") + g[6:]
    assert any("checksum" in e for e in gstin_errors(typo))


@pytest.mark.parametrize(
    ("value", "fragment"),
    [("27AAPFU0939F1Z", "15 characters"), ("27AAPFU0939F1XV", "format"), ("40AAPFU0939F1ZV", "state code")],
)
def test_gstin_errors(value: str, fragment: str) -> None:
    errs = gstin_errors(value)
    assert errs and fragment in " ".join(errs)


def test_pan() -> None:
    assert pan_errors("AAACT2727Q") == []
    assert pan_errors("AAAC2727Q") != []
    assert pan_from_gstin("27AAPFU0939F1ZV") == "AAPFU0939F"


@pytest.mark.parametrize(
    ("raw", "code"),
    [("Maharashtra", "27"), ("27", "27"), ("27-Maharashtra", "27"), ("Tamil Nadu", "33"),
     ("TN", "33"), ("7", "07"), ("Orissa", "21"), ("Atlantis", None), (None, None)],
)  # fmt: skip
def test_normalize_state(raw: str | None, code: str | None) -> None:
    assert normalize_state(raw) == code


@pytest.mark.parametrize(
    ("raw", "paise"),
    [("₹1,23,456.50", 12345650), ("Rs. 18,400/-", 1840000), ("50,00,000", 500000000),
     ("(1,000.00)", -100000), ("-0.45", -45), ("0.455", 46), ("abc", None), (None, None)],
)  # fmt: skip
def test_parse_money(raw: str | None, paise: int | None) -> None:
    assert parse_money_paise(raw) == paise


def test_parse_decimal() -> None:
    assert str(parse_decimal("1,20,000 PCS")) == "120000"
    assert str(parse_decimal("18%")) == "18"
    assert parse_decimal("n/a") is None


@pytest.mark.parametrize(
    ("words", "paise"),
    [
        ("Rupees Fifty Lakh Twelve Thousand and Fifty Paise Only", 501200050),
        ("INR One Hundred Twenty Five and Fifty Paise Only", 12550),
        ("Rupees Two Crore Five Lakh Only", 2050000000),
        ("Eighteen Thousand Four Hundred Rupees Only", 1840000),
        ("One Lakh Twenty-Three Thousand Four Hundred and Fifty Six Rupees Only", 12345600),
        ("Rupees Five Hundred and Five Only", 50500),
        ("Gibberish words", None),
    ],
)
def test_words_to_paise(words: str, paise: int | None) -> None:
    assert words_to_paise(words) == paise


def test_financial_year() -> None:
    assert financial_year(date(2026, 11, 13)) == "2026-27"
    assert financial_year(date(2027, 3, 31)) == "2026-27"
    assert financial_year(date(2027, 4, 1)) == "2027-28"

import logging

import pytest

from app.core.redaction import REDACTED, RedactingFilter, redact_text, redact_value


def test_redact_value_nested() -> None:
    data = {
        "name": "Tata Motors",
        "pan": "AAACT2727Q",
        "bank": {"bank_account_number": "123456784417", "bank_name": "HDFC"},
        "contacts": [{"phone": "9876543210", "email": "a@b.com"}],
        "upi_id": None,
    }
    out = redact_value(data)
    assert out["name"] == "Tata Motors"
    assert out["pan"] == REDACTED
    assert out["bank"] == {"bank_account_number": REDACTED, "bank_name": "HDFC"}
    assert out["contacts"][0] == {"phone": REDACTED, "email": "a@b.com"}
    assert out["upi_id"] is None  # nulls stay null


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("account 123456784417 saved", "123456784417"),
        ("PAN AAACT2727Q", "AAACT2727Q"),
        ("pay to acme@okhdfc", "acme@okhdfc"),
    ],
)
def test_redact_text(raw: str, must_not_contain: str) -> None:
    assert must_not_contain not in redact_text(raw)


def test_email_addresses_survive() -> None:
    assert "orders@tata.com" in redact_text("mail orders@tata.com")


def test_logging_filter_scrubs(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.redaction")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redaction"):
        logger.info("saving account %s", "123456784417")
    assert "123456784417" not in caplog.text
    assert "[number]" in caplog.text

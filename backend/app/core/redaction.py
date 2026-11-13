"""Redaction of sensitive data before it reaches logs or the audit log."""

import logging
import re
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "bank_account",
        "bank_account_number",
        "account_number",
        "upi_id",
        "pan",
        "phone",
        "mobile",
    }
)
REDACTED = "[redacted]"

_PATTERNS = [
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer [redacted]"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[pan]"),  # PAN
    (re.compile(r"\b[\w.\-]{2,}@[a-zA-Z]{2,}\b(?!\.)"), "[upi]"),  # UPI id (no TLD dot)
    (re.compile(r"\b\d{9,18}\b"), "[number]"),  # bank account / phone-like numbers
]


def redact_value(value: Any) -> Any:
    """Recursively replace values of sensitive keys."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_KEYS and v is not None else redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def redact_text(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter: scrubs secrets from every message before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        return True

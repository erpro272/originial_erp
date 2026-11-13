"""Single source of "today" so tests can pin the date."""

from datetime import UTC, date, datetime

_override: date | None = None


def today() -> date:
    return _override or datetime.now(UTC).astimezone().date()


def set_today(d: date | None) -> None:
    """Tests only."""
    global _override
    _override = d

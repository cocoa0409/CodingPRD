"""Logical clock (PRD §2.5).

The clock reads exactly `2026-09-01T00:00:00Z` before any clock operation and
never falls back to real system time. Two test-driving endpoints administer it:
`set_current_utc` (via `to_iso8601`) and `advance` (a whole-day count in the
inclusive range 1-3650).
"""
from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"
CLOCK_MIN_ADVANCE_DAYS = 1
CLOCK_MAX_ADVANCE_DAYS = 3650

_FMT = "%Y-%m-%dT%H:%M:%SZ"


class _Clock:
    def __init__(self):
        self.value = _parse(CLOCK_DEFAULT_UTC)

    def reset(self):
        self.value = _parse(CLOCK_DEFAULT_UTC)


def _parse(text: str) -> datetime:
    if not isinstance(text, str):
        raise ValueError("clock value must be an ISO-8601 string")
    cleaned = text.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt(when: datetime) -> str:
    """Render an instant in the clock's own no-fraction ISO 8601 form."""
    return when.astimezone(timezone.utc).strftime(_FMT)


clock = _Clock()


def now() -> datetime:
    return clock.value


def now_iso() -> str:
    return fmt(clock.value)


def set_current(to_iso8601) -> None:
    clock.value = _parse(to_iso8601)


def add_days(days: int) -> datetime:
    clock.value = clock.value + timedelta(days=days)
    return clock.value


def days_between(earlier: datetime, later: datetime) -> int:
    """Whole logical days elapsed between two instants."""
    return int((later - earlier).total_seconds() // 86400)


def parse(text) -> datetime:
    return _parse(text)


def reset() -> None:
    clock.reset()
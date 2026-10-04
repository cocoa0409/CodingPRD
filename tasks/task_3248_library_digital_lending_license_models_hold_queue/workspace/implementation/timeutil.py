from datetime import datetime, timezone, timedelta

_FMT = "%Y-%m-%dT%H:%M:%S.%f"


class Clock:
    """Deterministic logical clock. Never falls back to wall-clock."""

    def __init__(self):
        self._current = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt


CLOCK = Clock()


def parse_iso(value):
    """Parse ISO-8601 (with Z or offset) into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC at whole-second precision, e.g. 2026-09-01T00:00:00Z.

    The PRD writes every logical-clock literal in this exact form
    (e.g. the startup clock `2026-09-01T00:00:00Z`), so all logical-clock
    timestamps are rendered without fractional digits.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts_ms(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(_FMT)[:-3] + "Z"


def wall_now():
    """Real wall-clock timestamp for meta.api_request_timestamp."""
    return datetime.now(timezone.utc)


def round_half_up(x):
    """Round a numeric value half-up to whole units. Accepts int/float/Decimal."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(x):
    """Round half-up to 2 decimal places, returned as float."""
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

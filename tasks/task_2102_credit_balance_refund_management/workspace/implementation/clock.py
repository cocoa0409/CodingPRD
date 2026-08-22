"""Logical clock (PRD 2.5) and whole-day / rounding helpers (PRD 2.6)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD 2.5: at server startup the logical clock reads exactly 2026-08-01T00:00:00Z
# and never falls back to real wall-clock time.
STARTUP_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": STARTUP_INSTANT}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
    return _state["now"]


def reset():
    _state["now"] = STARTUP_INSTANT


def real_now():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    """PRD 2.6: adding N days means adding N periods of exactly 86400 seconds."""
    return dt + timedelta(seconds=86400 * days)


def whole_days(later, earlier):
    """PRD 2.6: whole days, floored."""
    if later is None or earlier is None:
        return 0
    delta = (later - earlier).total_seconds()
    return int(delta // 86400)


def round_half_up(numerator, denominator):
    """Exact rational rounding, half away from zero, to a whole cent."""
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

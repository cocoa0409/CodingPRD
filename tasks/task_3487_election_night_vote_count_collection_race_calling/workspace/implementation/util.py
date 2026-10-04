"""Parsing / formatting / numeric helpers (PRD §2.4 timestamps, §2.8
precision)."""
import uuid
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err

SIX_PLACES = Decimal("0.000001")


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g.
    2026-09-01T00:00:00.000Z (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_datetime(value):
    """Parse an ISO 8601 UTC instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO calendar date YYYY-MM-DD; returns a date or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def round6(numer, denom):
    """numer/denom to 6 decimal places, round-half-up, returned as float."""
    if denom == 0:
        denom = 1
    q = (Decimal(numer) / Decimal(denom)).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
    return float(q)


def round6_decimal(value):
    """Round a Decimal-compatible value to 6dp half-up, returned as float."""
    return float(Decimal(str(value)).quantize(SIX_PLACES, rounding=ROUND_HALF_UP))


def money_round(value):
    """Round a Decimal product half-up to whole cents -> int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_int(value):
    """True for a genuine JSON integer (bools excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def require_fields(body, fields):
    """ERR_INVALID_REQUEST when a required field is absent or null."""
    for f in fields:
        if f not in body or body[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def event_day_window(event_date_str):
    """[event_dateT00:00:00Z, (event_date+1d)T00:00:00Z) as datetimes."""
    d = date.fromisoformat(event_date_str)
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)

"""Small utilities: ids, timestamps (logical-clock based), Decimal helpers."""
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + secrets.token_hex(10)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on anything unparseable or non-string.
    Naive inputs (no offset) are treated as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if not s:
        raise ValueError("empty datetime")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"invalid ISO 8601 datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_decimal(value):
    """Convert a JSON number (int/float, never bool) to an exact Decimal."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")
    return Decimal(str(value))


def round_half_up_int(d):
    """Round a Decimal to the nearest integer, half up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_out(d):
    """Serialize a Decimal (or plain number) as a JSON number: int when integral."""
    if isinstance(d, Decimal):
        if d == d.to_integral_value():
            return int(d)
        return float(d)
    return d

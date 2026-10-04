"""Shared low-level helpers: ids, datetimes, decimal rounding."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def gen_id():
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def gen_request_id():
    """Envelope api_request_id: starts with req_ (PRD §2.2)."""
    return "req_" + uuid.uuid4().hex


def _format_millis_utc(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def wall_now_iso():
    """api_request_timestamp: server wall-clock UTC with three fractional digits."""
    return _format_millis_utc(datetime.now(timezone.utc))


def format_dt(dt):
    """Serialize an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return _format_millis_utc(dt)


def parse_datetime(value):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts date-only ("2026-09-01", read as midnight UTC), trailing "Z", and
    explicit offsets. Returns None when the value is not a parseable string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_cents(value):
    """Round a Decimal amount to whole cents, half up (PRD §2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of_cents(cents, pct):
    """round_half_up(cents * pct) with pct as Decimal/float/int.

    pct is stringified before becoming a Decimal so float inputs like 0.65
    become Decimal('0.65'), never the binary expansion.
    """
    return round_half_up_cents(Decimal(int(cents)) * Decimal(str(pct)))

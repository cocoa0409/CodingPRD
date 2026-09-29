"""Time, identifier and rounding helpers.

All datetimes crossing the API are ISO 8601 UTC strings with exactly three
fractional-second digits (PRD 2.4 / 2.5).
"""
import datetime as _dt
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

UTC = _dt.timezone.utc

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Bare UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def real_now():
    return _dt.datetime.now(tz=UTC)


def real_now_iso():
    return iso(real_now())


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def add_hours(dt, hours):
    return dt + _dt.timedelta(hours=hours)


def add_days(dt, days):
    return dt + _dt.timedelta(days=days)


def round_half_up(value):
    """Round a Decimal/int/Fraction half up to a whole number."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_of(amount, bps):
    """amount * bps / 10000, rounded half up to whole cents (PRD 2.7)."""
    return round_half_up(Decimal(int(amount)) * Decimal(int(bps)) / Decimal(10000))


def round_half_up_3(value):
    """Round a Decimal to three decimal places, half up (hours_elapsed_at_claim)."""
    return Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def sort_rows(rows):
    """Ascending created_at order with insertion sequence as tie breaker."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def latest(rows, keys):
    """Highest row by the supplied key extractors (all DESC), or None."""
    best = None
    best_key = None
    for row in rows:
        key = tuple(k(row) for k in keys)
        if best is None or key > best_key:
            best, best_key = row, key
    return best


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]

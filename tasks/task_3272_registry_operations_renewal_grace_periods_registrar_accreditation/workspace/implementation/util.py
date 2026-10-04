from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

EPOCH_DEFAULT = "2026-09-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO-8601 string (with trailing Z or offset) into an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, str):
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError("not an iso string")


def fmt_iso(dt):
    """Format an aware UTC datetime as ISO-8601 with three fractional digits and Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def is_leap_year(y):
    return (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)


def add_years(dt, years):
    """Add whole calendar years to a datetime, clamping Feb 29 to Feb 28."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def round_half_up_cents(value):
    """Round a Decimal (or int-convertible) to whole integer cents, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hash_token(tok):
    import hashlib
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()

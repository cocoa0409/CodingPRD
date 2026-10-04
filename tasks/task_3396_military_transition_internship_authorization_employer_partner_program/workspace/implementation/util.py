from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_iso_datetime(value):
    """Parse an ISO 8601 string into an aware UTC datetime; None on failure.
    Accepts date-only strings (treated as midnight UTC) and trailing 'Z'."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse a date-precision ISO value into a datetime.date; None on failure."""
    dt = parse_iso_datetime(value)
    if dt is None:
        return None
    return dt.date()


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def round2(value):
    """Round half-up to exactly 2 decimal places; returned as a JSON number."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def serialize_value(v):
    if isinstance(v, datetime):
        return fmt_ts(v)
    if isinstance(v, date):
        return fmt_date(v)
    if isinstance(v, list):
        return [serialize_value(x) for x in v]
    if isinstance(v, dict):
        return {k: serialize_value(x) for k, x in v.items()}
    return v


def serialize(entity):
    """Serialize a stored entity dict: datetimes/dates to strings, drop internal keys."""
    return {k: serialize_value(v) for k, v in entity.items() if not k.startswith("_")}

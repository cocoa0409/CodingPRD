"""Numeric, date and formatting primitives shared across the service."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from datetime import datetime, date, timezone
import math


def D(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(int(x))
    return Decimal(str(x))


def rhu(x, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    quant = Decimal(1).scaleb(-places)
    return D(x).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(x):
    return int(rhu(x, 0))


def rhu_f(x, places):
    return float(rhu(x, places))


def clamp(x, lo, hi):
    xv = D(x)
    lov = D(lo)
    hiv = D(hi)
    if xv < lov:
        return lov
    if xv > hiv:
        return hiv
    return xv


def dec_floor(x):
    return int(D(x).to_integral_value(rounding=ROUND_FLOOR))


def parse_date(s):
    """Strict YYYY-MM-DD parse; returns a date or None."""
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def days_between(a, b):
    """Signed whole-day difference b - a."""
    return (b - a).days


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    return d.isoformat()


def parse_instant(s):
    """Parse an ISO 8601 instant; returns a tz-aware datetime or None."""
    if not isinstance(s, str) or not s:
        return None
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        d = parse_date(s)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def num_out(x):
    """Render a Decimal as int when integral, else float."""
    d = D(x)
    if d == d.to_integral_value():
        return int(d)
    return float(d)

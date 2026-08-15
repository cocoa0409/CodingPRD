"""Parsing, formatting, and small arithmetic helpers (PRD §2.4, §2.6)."""

import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err, ERR_INVALID_REQUEST

_DT_FMT = "%Y-%m-%dT%H:%M:%S"
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(_DT_FMT) + ".%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def parse_date(value):
    """Strict ISO calendar date (YYYY-MM-DD). Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "expected an ISO date string, got %r" % (value,))
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "unparsable date: %r" % (value,))


def parse_datetime(value):
    """ISO 8601 datetime; naive values are read as UTC. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "expected an ISO datetime string, got %r" % (value,))
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "unparsable datetime: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_time(value):
    """HH:MM 24-hour clock time. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, "expected HH:MM 24h time, got %r" % (value,))
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def age_in_years(birth, on_date):
    """Whole years of age on `on_date` by calendar month/day comparison.

    A birthday exactly on `on_date` counts as already turned.
    """
    age = on_date.year - birth.year
    if (on_date.month, on_date.day) < (birth.month, birth.day):
        age -= 1
    return age


def ceil_div(a, b):
    """ceil(a / b) for non-negative integers a, b with b >= 1."""
    return -(-a // b)


def round4(numer, denom):
    """round_half_up(numer / denom, 4) returned as float."""
    if denom == 0:
        return 0.0
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def round4_dec(numer, denom):
    """round_half_up(numer / denom, 4) returned as Decimal (for tier thresholds)."""
    if denom == 0:
        return Decimal("0.0000")
    return (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

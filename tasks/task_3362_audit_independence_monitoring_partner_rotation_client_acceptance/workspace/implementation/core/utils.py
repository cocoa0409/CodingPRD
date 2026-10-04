"""Identifier minting, temporal arithmetic and numeric rounding helpers."""

import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALPHANUM = string.ascii_lowercase + string.digits


def new_id():
    """Server-minted resource identifier: a bare UUID, no prefix."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Timestamp rendering
# ---------------------------------------------------------------------------
def format_timestamp(value):
    """Common-field rendering: ISO 8601 UTC with exactly three fractional digits."""
    value = ensure_utc(value)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def format_instant(value):
    """Entity-datetime rendering: ISO 8601 UTC, fraction only when non-zero."""
    value = ensure_utc(value)
    if value.microsecond:
        return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value):
    """Parse an ISO 8601 instant; returns None when the value is not a string."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return ensure_utc(parsed)


def parse_date_only(value):
    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Calendar arithmetic
# ---------------------------------------------------------------------------
def add_months(value, months):
    """Add whole months preserving the day of month (clamped to month length)."""
    value = ensure_utc(value)
    months = int(months)
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def months_between(start, end):
    """Whole months from start to end, floored."""
    if start is None or end is None:
        return 0
    start = ensure_utc(start)
    end = ensure_utc(end)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    if months < 0:
        return 0
    return months


def add_days(value, days):
    return ensure_utc(value) + timedelta(days=int(days))


def days_between(start, end):
    return (ensure_utc(end) - ensure_utc(start)).days


# ---------------------------------------------------------------------------
# Numeric rounding
# ---------------------------------------------------------------------------
def round_half_up(value, places=0):
    """Round half away from zero, returning a Decimal quantised as requested."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def money_score(value):
    """2-decimal score rendering as a float, round-half-up."""
    return float(round_half_up(value, 2))


def whole_dollar_cents(cents):
    """Round a cent amount to the nearest whole dollar, round-half-up."""
    dollars = round_half_up(Decimal(str(cents)) / Decimal(100), 0)
    return int(dollars) * 100


def to_decimal(value, default="0"):
    try:
        if isinstance(value, bool):
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)

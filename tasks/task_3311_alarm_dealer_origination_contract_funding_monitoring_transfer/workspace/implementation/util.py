"""Shared helpers: logical clock, timestamp format, round-half-up, calendar maths.

PRD §2.4 — the service never reads wall-clock time. The logical clock is fixed at
2026-09-01T00:00:00Z at boot and is only ever moved by the PlatformAdmin
clock-setting capability. Every temporal rule is evaluated against it.
"""

import calendar
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD §2.4: the logical clock is fixed at 2026-09-01T00:00:00Z when the server starts.
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:?\d{2})?$"
)


def mint_id():
    """PRD §2.5 — a server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.2, §2.5)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, zone = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    tzinfo = timezone.utc
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        z = zone[1:].replace(":", "")
        tzinfo = timezone(sign * timedelta(hours=int(z[:2]), minutes=int(z[2:4])))
    return datetime(int(year), int(month), int(day), int(hour), int(minute),
                    int(second), micro, tzinfo=tzinfo).astimezone(timezone.utc)


def round_half_up(value):
    """PRD §2.7 — round half-up. Returns an int when handed an int-able value."""
    if isinstance(value, Decimal):
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_cents(value):
    return round_half_up(value)


def round_percent2(value):
    """Percent with two decimal places, round-half-up (PRD §2.7). Returns a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _add_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return coerce_dt(dt) + timedelta(days=days)


def add_months(dt, months):
    return _add_months(coerce_dt(dt), months)


def month_label(dt):
    """A logical month label in YYYY-MM (PRD §2.4)."""
    dt = coerce_dt(dt)
    if dt is None:
        return None
    return dt.strftime("%Y-%m")


def coerce_dt(value):
    """Rows store instants as ISO strings; accept either form and return a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return parse_ts(value)


def whole_calendar_days(start, end):
    """Whole calendar days between two logical instants (a date difference)."""
    start = coerce_dt(start)
    end = coerce_dt(end)
    if start is None or end is None:
        return 0
    return (end.date() - start.date()).days


def whole_calendar_months(start, end):
    """Whole calendar months elapsed between two logical instants."""
    start = coerce_dt(start)
    end = coerce_dt(end)
    if start is None or end is None:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def within_trailing_months(instant, now, months):
    """True when `instant` falls inside the trailing window ending at `now`.

    The window runs from `now` minus `months` whole calendar months through `now`
    inclusive (PRD §2.4: a trailing window is a count of whole calendar months
    measured back from the logical clock's current instant).
    """
    instant = coerce_dt(instant)
    if instant is None:
        return False
    now = coerce_dt(now)
    return _add_months(now, -months) <= instant <= now
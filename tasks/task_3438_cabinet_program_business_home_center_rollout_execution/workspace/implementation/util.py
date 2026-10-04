"""Time, ISO-week and rounding helpers (pure python, no flask)."""
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return iso3(now_dt())


def format_clock(dt):
    """Canonical clock echo: seconds precision when the instant is whole, else ms."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return iso3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 datetime string; returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_week(value):
    """'YYYY-Www' -> (iso_year, iso_week) tuple, or None when malformed."""
    if not isinstance(value, str):
        return None
    match = WEEK_RE.match(value.strip())
    if not match:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    try:
        datetime.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    return (year, week)


def week_of(dt):
    iso = dt.astimezone(timezone.utc).isocalendar()
    return "{:04d}-W{:02d}".format(iso[0], iso[1])


def add_weeks(week_str, n):
    """Advance an ISO week string by n weeks (n may be negative)."""
    yw = parse_week(week_str)
    if yw is None:
        return None
    monday = datetime.fromisocalendar(yw[0], yw[1], 1) + timedelta(weeks=n)
    iso = monday.isocalendar()
    return "{:04d}-W{:02d}".format(iso[0], iso[1])


def round_half_up_cents(value):
    """Round a Decimal-compatible value half-up to whole cents (int)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

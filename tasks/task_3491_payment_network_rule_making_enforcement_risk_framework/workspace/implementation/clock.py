"""Logical clock, timestamp rendering families, and date/banking-day helpers.

No Flask imports here so every other module (envelope, validation, domains)
can depend on this module without import cycles.
"""
import re
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------

_BOOT_TIME = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    """Server-side deterministic clock. Never falls back to wall-clock time."""

    def __init__(self):
        self._now = _BOOT_TIME

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set_now(self, dt):
        self._now = dt


CLOCK = LogicalClock()

# ---------------------------------------------------------------------------
# Timestamp rendering (PRD section 2.4 — two families)
# ---------------------------------------------------------------------------


def render_ts3(dt):
    """Bookkeeping family: api_request_timestamp / created_at / updated_at.

    Always ISO 8601 UTC with exactly three fractional-second digits.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def render_ts(dt):
    """Domain family: rendered exactly as the logical clock reads.

    No fractional digits when the clock carries none; otherwise preserve the
    precision the clock was set with (3-digit millis, else 6-digit micros).
    """
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = dt.microsecond
    if micro:
        if micro % 1000 == 0:
            base += ".%03d" % (micro // 1000)
        else:
            base += ".%06d" % micro
    return base + "Z"


def render_date(d):
    """Date-only fields render as ISO YYYY-MM-DD."""
    if d is None:
        return None
    return d.isoformat()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PERIOD_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Strict YYYY-MM-DD date parse; returns a date or None."""
    if not isinstance(value, str):
        return None
    if not _DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def is_valid_period(value):
    return isinstance(value, str) and _PERIOD_RE.fullmatch(value) is not None


def period_of_date(d):
    return "%04d-%02d" % (d.year, d.month)


def period_of_datetime(dt):
    return "%04d-%02d" % (dt.year, dt.month)


# ---------------------------------------------------------------------------
# Banking days (Mon-Fri, no holiday calendar)
# ---------------------------------------------------------------------------


def banking_days_between(start, end):
    """Count banking days strictly after `start`, up to and including `end`.

    A return settled on `start` with a timeframe of N banking days is accepted
    while banking_days_between(settled_date, today) <= N.
    """
    if end <= start:
        return 0
    count = 0
    d = start + timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def hhmm(dt):
    """(hour, minute) tuple for HH:MM-to-the-minute comparisons."""
    return (dt.hour, dt.minute)


def parse_hhmm(value):
    """Parse an 'HH:MM' 24h string into (hour, minute), or None."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", value)
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)))

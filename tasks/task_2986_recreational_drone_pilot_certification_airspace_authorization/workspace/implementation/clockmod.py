"""Logical clock (PRD 2.4) plus datetime parsing / formatting helpers.

Every temporal decision in the service reads this logical clock.  Real
wall-clock time is used only for the envelope's api_request_timestamp.
"""

import calendar
from datetime import datetime, timedelta, timezone

from errors import ApiError

START_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self.current = START_UTC

    def now(self):
        return self.current

    def set(self, value):
        # PRD 2.4: the clock is monotonic and forward-only; rewinding, or
        # setting it to the instant it already holds, is refused.
        if value <= self.current:
            raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN")
        previous = self.current
        self.current = value
        return previous


clock = LogicalClock()


def fmt_dt(value):
    """Whole-second ISO 8601 UTC with a trailing Z (PRD 2.4)."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt_ms(value):
    """ISO 8601 UTC with exactly three fractional digits (envelope only)."""
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def parse_dt(raw):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str) or isinstance(raw, bool):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_months(value, months):
    """Calendar-month arithmetic with day clamping, time of day preserved."""
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def add_days(value, days):
    return value + timedelta(days=days)


def add_minutes(value, minutes):
    return value + timedelta(minutes=minutes)

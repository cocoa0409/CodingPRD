"""The server-controlled logical clock (PRD §2.11).

Time never comes from the wall clock: on startup the clock reads
2026-09-01T00:00:00Z and it moves only when a PlatformAdmin calls
POST /agency-network/_clock/set_current_utc.  Every timestamp the server mints
is read from here.
"""

import uuid
from datetime import datetime, timezone

STARTUP_UTC = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Set by install() at application start-up; deliberately never seeded with any
# entity data — this is only the clock's initial instant.
_current = STARTUP_UTC


def install():
    """Reset the clock to its startup instant and drop the request-id counter."""
    global _current
    _current = STARTUP_UTC


def now():
    return _current


def set_current(to_iso8601):
    global _current
    _current = parse_iso(to_iso8601)
    return _current


def parse_iso(value):
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt=None):
    """ISO 8601 UTC with exactly three fractional digits, e.g. ...00.123Z."""
    dt = dt or _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-month arithmetic; day-of-month clamps to the target month's end."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24].upper()
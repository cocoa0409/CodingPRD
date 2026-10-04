"""Logical clock and timestamp helpers.

Business timestamps (last_contact_at, filed_at, decided_at, exoneration_date,
the contact-overdue sweep, deadline comparisons) read the server-side logical
clock defined in PRD section 2.4. Before any set call the clock reads exactly
2026-09-01T00:00:00Z and never falls back to wall-clock time.

The logical clock keeps the exact raw string supplied by the caller so that
timestamps written from it echo that string verbatim; comparisons always use
the parsed datetime.

created_at / updated_at / meta.api_request_timestamp are system metadata
timestamps (PRD 2.5 / 2.2): they use the wall clock, rendered as ISO 8601 UTC
with three fractional digits, and are kept strictly monotonic so that
created_at ordering is deterministic.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 date/datetime into an aware UTC datetime.

    Returns None when the value is not a parseable ISO 8601 string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._raw = DEFAULT_CLOCK_ISO
        self._dt = parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, raw):
        dt = parse_iso(raw)
        if dt is None:
            return False
        self._raw = raw.strip()
        self._dt = dt
        return True

    def now_dt(self):
        return self._dt

    def stamp(self):
        return self._raw


CLOCK = LogicalClock()


_last_wall = None


def wall_now_iso():
    """ISO 8601 UTC wall timestamp with three fractional digits.

    Strictly monotonic: if the wall clock would produce a timestamp <= the
    previous one, the previous value plus one millisecond is used instead.
    """
    global _last_wall
    t = datetime.now(timezone.utc)
    s = t.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (t.microsecond // 1000)
    if _last_wall is not None and s <= _last_wall:
        prev = datetime.strptime(_last_wall, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        t = prev + timedelta(milliseconds=1)
        s = t.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (t.microsecond // 1000)
    _last_wall = s
    return s

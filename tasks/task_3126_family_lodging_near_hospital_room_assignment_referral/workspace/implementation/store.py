"""In-memory data store and logical clock.

Storage is in-memory only (Python dicts keyed by id). No disk persistence of
any kind. The store starts empty on every boot; nothing is seeded.
"""
import itertools
import re
import uuid
from datetime import datetime, timezone

db = {
    "hospitals": {},
    "houses": {},
    "rooms": {},
    "families": {},
    "referrals": {},
    "stay_requests": {},
    "stays": {},
    "guests": {},
    "screenings": {},
    "contributions": {},
    "volunteer_groups": {},
    "meal_shifts": {},
    "care_spaces": {},
    "bookings": {},
    "donations": {},
}

_seq = itertools.count(1)

# Logical clock: before any client call it reads exactly 2026-09-01T00:00:00Z
# and never falls back to wall-clock time.
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def today():
    return _clock.date()


def iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_clock)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_date(s):
    """Parse a strict YYYY-MM-DD date; return None when invalid."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        parts = s.split("-")
        from datetime import date

        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def parse_datetime(s):
    """Parse an ISO 8601 datetime; naive values are assumed UTC. None if invalid."""
    if not isinstance(s, str) or not _DT_RE.match(s):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

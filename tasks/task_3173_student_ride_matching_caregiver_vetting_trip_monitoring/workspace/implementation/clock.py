"""The logical clock, ISO timestamp formatting and date helpers.

PRD section 2.10: at server start the logical clock reads exactly
2026-09-01T00:00:00Z and it never falls back to the host wall clock.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Mutable single-value store; deliberately reset to the fixed default on every
# process start so a fresh boot carries no temporal state forward.
_clock = {"now": None}


def reset_clock():
    _clock["now"] = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_utc():
    if _clock["now"] is None:
        reset_clock()
    return _clock["now"]


def set_clock(iso):
    """Set the logical clock from an ISO 8601 instant."""
    _clock["now"] = parse_dt(iso)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp():
    return fmt_dt(now_utc())


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        raise ValueError("missing datetime")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD) into a date."""
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def clock_date():
    return now_utc().date()


def date_start(d):
    """The instant a date begins, at UTC midnight."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def date_end(d):
    """The last instant of a date, at UTC 23:59:59.999999."""
    return date_start(d) + timedelta(days=1) - timedelta(microseconds=1)


def new_id():
    """A bare UUID, no type prefix (PRD section 2.7)."""
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return "req_" + suffix
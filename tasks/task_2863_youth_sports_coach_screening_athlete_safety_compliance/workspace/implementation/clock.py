"""The logical clock (PRD section 2.5).

On server start the clock stands at exactly 2026-08-01T00:00:00Z and every rule
that consults the clock sees that instant until an NgbAdmin repositions it.
All instants are ISO 8601 UTC with three fractional digits.
"""

import re
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_CLOCK


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable.

    A bare calendar date is accepted and read as midnight UTC.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if _DATE_ONLY.match(raw):
        try:
            d = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
        return d.replace(tzinfo=timezone.utc)
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Returns None when invalid."""
    if not isinstance(value, str) or not _DATE_ONLY.match(value.strip()):
        return None
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return value.strip()


def iso(dt):
    """Format an instant as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def plus_days(dt, days):
    """Day arithmetic adds exact multiples of 24 hours (PRD section 2.5)."""
    if dt is None:
        return None
    return dt + timedelta(days=days)


def plus_years(dt, years):
    """Retention horizons are whole years expressed as exact 365-day multiples
    is NOT used: a year here is a calendar year offset."""
    if dt is None:
        return None
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # 29 February
        return dt.replace(year=dt.year + years, day=28)


def real_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"

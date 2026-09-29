"""The logical clock (PRD 2.4).

Nothing in this system reads wall-clock time.  Before any request has moved it
the logical clock reads exactly 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timedelta

STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0)

_STATE = {"now": STARTUP_DEFAULT}


def now():
    return _STATE["now"]


def set_now(dt):
    _STATE["now"] = dt


def now_iso():
    return iso(_STATE["now"])


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_instant(raw):
    """Parse an ISO-8601 UTC instant.  Returns a naive UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if text.endswith("Z") or text.endswith("z"):
            body = text[:-1]
            dt = datetime.fromisoformat(body)
            if dt.tzinfo is not None:
                dt = dt.astimezone(tz=None).replace(tzinfo=None)
            return dt
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            offset = dt.utcoffset() or timedelta(0)
            dt = dt.replace(tzinfo=None) - offset
        return dt
    except (ValueError, TypeError):
        return None


def date_str(dt):
    return dt.strftime("%Y-%m-%d")


def minutes_of_day(dt):
    return dt.hour * 60 + dt.minute


def whole_minutes_between(earlier, later):
    delta = later - earlier
    total = int(delta.total_seconds() // 60)
    return total if total > 0 else 0

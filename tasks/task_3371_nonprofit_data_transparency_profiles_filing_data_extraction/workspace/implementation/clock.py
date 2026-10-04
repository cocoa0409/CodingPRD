"""The logical clock and the timestamp helpers used across the service.

The server never reads wall-clock time.  It starts with the logical clock fixed
at 2026-09-01T00:00:00Z and only an operator may advance it (PRD 2.4).
"""

from datetime import datetime, timedelta, timezone

# PRD 2.4: the server starts with its logical clock fixed at this instant.
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK_START_RAW = "2026-09-01T00:00:00Z"

_state = {"now": CLOCK_START, "raw": CLOCK_START_RAW}


def now():
    """The current logical-clock instant (timezone-aware, UTC)."""
    return _state["now"]


def now_raw():
    """The clock instant exactly as the operator last supplied it."""
    return _state["raw"]


def set_now(instant, raw=None):
    _state["now"] = instant
    _state["raw"] = raw if raw is not None else fmt_dt(instant)


def reset():
    _state["now"] = CLOCK_START
    _state["raw"] = CLOCK_START_RAW


def fmt_dt(instant):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD 2.5)."""
    instant = instant.astimezone(timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(instant, days):
    return instant + timedelta(days=days)


def days_between(later, earlier):
    """Whole days from ``earlier`` to ``later``, truncated toward zero."""
    delta = later - earlier
    return delta.days if delta.days >= 0 else -((-delta).days)


def floor_days(later, earlier):
    """Whole days elapsed from ``earlier`` to ``later``, floored at zero."""
    delta = later - earlier
    total = delta.days + (delta.seconds / 86400.0)
    return int(total) if total > 0 else 0

"""The logical clock. Never reads wall-clock time."""
from datetime import datetime, timedelta, timezone

DEFAULT_ISO = "2026-09-01T00:00:00Z"

_state = {"now": None}


def parse_iso(value):
    if value is None:
        return None
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


def default_now():
    return parse_iso(DEFAULT_ISO)


def now():
    if _state["now"] is None:
        _state["now"] = default_now()
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = None


def today():
    return now().replace(hour=0, minute=0, second=0, microsecond=0)


def days_elapsed(earlier, later=None):
    """Whole days by floor division of elapsed seconds."""
    if earlier is None:
        return 0
    later = later or now()
    delta = later - earlier
    return int(delta.total_seconds()) // 86400


def add_days(dt, days):
    return dt + timedelta(days=days)


def complete_months(start, end):
    """Completed whole calendar months between two instants."""
    if start is None or end is None or end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
        if months < 0:
            months = 0
    return months
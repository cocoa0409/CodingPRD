"""The logical clock.

PRD SS2.11: the platform never reads wall-clock time. The clock starts at
2026-09-01T00:00:00Z and only advances through POST /v1/_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timedelta, timezone

STARTUP_INSTANT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Module-level single logical instant; mutated only by the clock endpoint.
_current = STARTUP_INSTANT


def current():
    """The current logical instant as an aware UTC datetime."""
    return _current


def set_current(dt):
    global _current
    _current = dt


def parse(value):
    """Parse an ISO 8601 string into an aware UTC datetime (naive -> UTC)."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD SS2.2).

    Tolerates an already-formatted string so serialisation is idempotent for
    fields stored as ISO text (for example an order's composed_at).
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso():
    return iso(_current)


def add_days(dt, days):
    """Whole-day instant arithmetic, preserving the time of day."""
    return dt + timedelta(days=days)


def whole_days_between(start, end):
    """Floored count of whole days from start to end."""
    return int((end - start).total_seconds() // 86400)


def new_id():
    """Server-minted unique identifier with no type prefix (PRD SS2.4)."""
    return str(uuid.uuid4())
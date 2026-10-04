"""The server-side logical clock (PRD 2.4).

All temporal rules — submission windows, review dates, quote validity,
certification expiry, occupancy intervals, markdown depth, launch timing —
read this clock, never wall-clock time. Before it is set it reads exactly
2026-09-01T00:00:00Z. All "stamped" resource timestamps (created_at,
updated_at, selected_at, submitted_at, accepted_at, committed_at,
launched_at, evaluated_at) are logical-clock instants.
"""
from datetime import datetime, timezone

from core.constants import CLOCK_DEFAULT_ISO


def _parse_initial(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


_current = _parse_initial(CLOCK_DEFAULT_ISO)


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return _current


def set_now(dt):
    global _current
    _current = dt


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable datetime string. Naive
    inputs are interpreted as UTC.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits (PRD 2.5).

    Used for created_at / updated_at only — the two fields PRD 2.5 pins to
    three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def fmt_instant(dt):
    """Render a logical-clock instant exactly as the clock reads (PRD 2.4:
    "reads exactly 2026-09-01T00:00:00Z") — no fractional digits.

    Used for every stamped / computed / input datetime field (selected_at,
    submitted_at, accepted_at, committed_at, launched_at, evaluated_at,
    cert_expires_at, due_at, valid_until, window/occupancy bounds, ...),
    which PRD 2.5 defines as logical-clock instants."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def wallclock_now_iso():
    """Wall-clock timestamp for response meta.api_request_timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )

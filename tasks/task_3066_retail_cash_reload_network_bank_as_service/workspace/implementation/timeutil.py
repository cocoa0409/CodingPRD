"""The server's logical clock.

On startup the clock reads exactly 2026-09-01T00:00:00Z and it never falls back
to real time.  Every deadline, trailing window, due date and epoch index is
computed from that fixed default until an operator sets a different instant
through the admin-only clock endpoint.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = DEFAULT_CLOCK


def parse(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
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
    """ISO 8601 UTC with exactly three fractional digits.

    Used for the system-managed common properties (`created_at`, `updated_at`)
    and the response envelope, which PRD 2.2 / 2.5 pin to three fractional
    digits.
    """
    if dt is None:
        return None
    frac = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % frac


def iso_instant(dt):
    """A domain clock stamp: the clock instant rendered as it was supplied.

    PRD 2.9 gives the logical clock as an integer-second ISO instant
    (`2026-09-01T00:00:00Z`) and describes every domain datetime field - the
    stamps on loads, accounts, allocations and deadlines - as recording "the
    current clock instant".  The three-fractional-digit rule of PRD 2.5 is
    scoped to the common properties alone, so these stamps carry no fractional
    part when the instant has none.
    """
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    frac = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % frac


def now_iso():
    return iso(now())


def epoch_index_of(dt):
    """Logical-day bucket index for an instant (UTC day ordinal)."""
    return dt.astimezone(timezone.utc).date().toordinal()


def current_epoch_index():
    return epoch_index_of(now())


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_days(dt, days):
    return dt + timedelta(days=days)
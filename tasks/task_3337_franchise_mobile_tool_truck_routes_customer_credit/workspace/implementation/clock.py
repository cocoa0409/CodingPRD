"""The logical clock and the Monday-anchored weekly cadence.

Nothing in this service reads the host clock: every temporal value is derived
from a single logical clock whose startup value is exactly 2026-09-01T00:00:00Z.
"""

from datetime import datetime, timedelta, timezone

from errors import fail

# Startup default of the logical clock — the instant the service reads before
# any call to the clock capability.
DEFAULT_UTC = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_UTC}

WEEK = timedelta(days=7)


def now():
    """The current logical-clock instant."""
    return _state["now"]


def set_now(instant):
    """Move the logical clock forward. Backwards motion is rejected."""
    if instant < _state["now"]:
        fail("ERR_WEEK_CLOCK_BEHIND")
    _state["now"] = instant


def reset():
    _state["now"] = DEFAULT_UTC


def parse_utc(text):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(text, str) or not text:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 string.")
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "current_utc is not a valid ISO 8601 instant.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (instant.astimezone(timezone.utc).microsecond // 1000)


def fmt_week(instant):
    """ISO 8601 UTC at second resolution.

    Week-valued fields, the route schedule anchor, the clock capability's own
    response and the instants stamped straight from the logical clock all carry
    this representation; only `created_at`, `updated_at` and
    `api_request_timestamp` carry the three fractional digits of Section 2.5.
    """
    if instant is None:
        return None
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def week_start(instant):
    """Monday 00:00:00Z of the week containing the instant."""
    if instant is None:
        return None
    day = instant.astimezone(timezone.utc)
    day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def current_week_start():
    return week_start(now())


def is_monday_midnight(instant):
    return (instant.weekday() == 0 and instant.hour == 0
            and instant.minute == 0 and instant.second == 0
            and instant.microsecond == 0)


def route_anchor(visit_weekday, reference=None):
    """Most recent occurrence of visit_weekday at 08:00:00Z strictly before now."""
    reference = reference or now()
    candidate = week_start(reference) + timedelta(days=visit_weekday - 1, hours=8)
    while candidate >= reference:
        candidate -= WEEK
    return candidate


def months_between(start_week, end_week):
    """Whole calendar months elapsed between two Monday 00:00:00Z instants."""
    if start_week is None or end_week is None:
        return 0
    return (end_week.year - start_week.year) * 12 + (end_week.month - start_week.month)

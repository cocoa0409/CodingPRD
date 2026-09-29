"""Logical clock, date/instant handling and exact integer arithmetic helpers.

PRD 2.10: time is a server-side logical clock that reads exactly
2026-08-01T00:00:00Z before any caller sets it and never falls back to the
host wall clock.

PRD 2.4: no floating point anywhere.  Ratio/capacity arithmetic uses floor
division; settlement arithmetic rounds halves away from zero.
"""

import datetime as _dt
import itertools
import re

UTC = _dt.timezone.utc

_DEFAULT_CLOCK = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": _DEFAULT_CLOCK}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_seq_counter = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence, used as the stable tie-break for
    created_at ordering (the logical clock can stamp identical instants)."""
    return next(_seq_counter)


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------
def reset_clock():
    _state["now"] = _DEFAULT_CLOCK


def set_clock(dt):
    _state["now"] = dt.astimezone(UTC)


def now_dt():
    return _state["now"]


def now_iso():
    return fmt_instant(_state["now"])


def clock_date():
    return _state["now"].astimezone(UTC).date()


# --------------------------------------------------------------------------
# formatting / parsing
# --------------------------------------------------------------------------
def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 UTC instant.  Returns None when malformed."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def fmt_date(d):
    return d.isoformat()


def add_days(date_str, days):
    d = parse_date(date_str)
    if d is None:
        return None
    return fmt_date(d + _dt.timedelta(days=days))


def day_diff(later_str, earlier_str):
    """Whole calendar days between two YYYY-MM-DD strings."""
    a = parse_date(later_str)
    b = parse_date(earlier_str)
    if a is None or b is None:
        return 0
    return (a - b).days


# --------------------------------------------------------------------------
# arithmetic
# --------------------------------------------------------------------------
def floor_div(numerator, denominator):
    """Exact integer quotient; a zero denominator yields 0 (PRD 2.4)."""
    if denominator == 0:
        return 0
    return numerator // denominator


def round_half_up(numerator, denominator):
    """Evaluate numerator/denominator as an exact rational and round halves
    away from zero.  All quantities in this system are non-negative."""
    if denominator == 0:
        return 0
    if numerator < 0:
        return -((-2 * numerator + denominator) // (2 * denominator))
    return (2 * numerator + denominator) // (2 * denominator)

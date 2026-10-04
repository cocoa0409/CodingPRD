"""Logical clock (PRD section 2.4) and the two timestamp rendering families.

The logical clock never reads wall-clock time. Before any administrative call
to POST /_clock/set_current_utc it reads exactly 2026-09-01T00:00:00Z.

Rendering families (PRD section 2.4):
  * system family  - created_at / updated_at / api_request_timestamp:
                     ISO 8601 UTC with exactly three fractional digits.
  * domain family  - every event timestamp populated from the logical clock:
                     rendered exactly as the clock reads (no forced fractional
                     digits; 'Z' suffix; fractional seconds preserved when the
                     clock was set with them).
"""
import re
from datetime import date, datetime, timedelta, timezone

from constants import CLOCK_START_ISO

_state = {"now": None}


def now():
    """Current logical-clock reading as an aware UTC datetime."""
    if _state["now"] is None:
        _state["now"] = parse_datetime(CLOCK_START_ISO)
    return _state["now"]


def set_now(value):
    _state["now"] = value


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or a numeric offset, with or without fractional
    seconds. A naive value is treated as UTC. Returns None when unparseable.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a plain ISO YYYY-MM-DD calendar date. Returns None when invalid."""
    if not isinstance(value, str):
        return None
    if not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def render_system(value):
    """System family: ISO 8601 UTC with exactly three fractional digits."""
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(value.microsecond // 1000)


def render_domain(value):
    """Domain family: rendered as the clock reads (Z suffix, no forced millis)."""
    value = value.astimezone(timezone.utc)
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    micros = value.microsecond
    if micros == 0:
        return base + "Z"
    if micros % 1000 == 0:
        return base + ".{:03d}Z".format(micros // 1000)
    return base + ".{:06d}Z".format(micros)


def render_date(value):
    """Calendar-date field: plain ISO YYYY-MM-DD."""
    return value.isoformat()


def days_from(value, days):
    return value + timedelta(days=days)

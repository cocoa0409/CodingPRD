"""Server-maintained logical clock plus ISO-8601 helpers (PRD section 2.4).

The logical clock starts at exactly 2026-09-01T00:00:00Z, never falls back to
wall-clock time, and moves only via POST /_clock/set_current_utc. Values are
stored as the raw strings supplied by the caller (arbitrary values accepted,
monotonicity not enforced); they are parsed only for comparisons.
"""

from datetime import datetime, timezone

from constants import LOGICAL_CLOCK_DEFAULT

_current_utc = LOGICAL_CLOCK_DEFAULT


def get_clock():
    return _current_utc


def set_clock(value):
    global _current_utc
    _current_utc = value


def parse_iso(value):
    """Parse an ISO-8601 string into an aware datetime; None if unparseable."""
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
    return parsed


def clock_dt():
    """The current logical clock as an aware datetime (None if unparseable)."""
    return parse_iso(_current_utc)


def wall_now_iso():
    """Wall-clock UTC now, ISO 8601 with three fractional digits and Z suffix.

    Used for system-managed fields (created_at/updated_at, section 2.5) and
    the envelope's api_request_timestamp (section 2.2).
    """
    now = datetime.now(timezone.utc)
    return "%s.%03dZ" % (now.strftime("%Y-%m-%dT%H:%M:%S"), now.microsecond // 1000)

"""Server-side logical clock (PRD §2.4). Never falls back to wall clock.

Boots at DEFAULT_CLOCK_ISO. Set-anywhere semantics: the set endpoint accepts any
ISO-8601 instant, past or future, with no monotonicity rejection.
"""

from datetime import datetime, timezone

from constants import DEFAULT_CLOCK_ISO

_current = None


def parse_iso(value):
    """Parse an ISO-8601 instant to an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    global _current
    if _current is None:
        _current = parse_iso(DEFAULT_CLOCK_ISO)
    return _current


def set_now(dt):
    global _current
    _current = dt


def reset():
    global _current
    _current = parse_iso(DEFAULT_CLOCK_ISO)


def iso_z(dt):
    """Business-timestamp format: seconds precision, fractional digits only when
    the instant carries them. Matches the clock's own echo format."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += ".%03d" % (dt.microsecond // 1000)
    return base + "Z"


def iso_ms(dt):
    """created_at / updated_at / envelope-meta format: always three fractional
    digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def add_years(dt, years):
    """Add whole calendar years; Feb 29 clamps to Feb 28 on non-leap targets."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


reset()

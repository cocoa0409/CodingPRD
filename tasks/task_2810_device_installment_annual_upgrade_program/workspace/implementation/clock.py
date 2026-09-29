"""Server-controlled logical clock (PRD 2.4).

Every instant the API records is read from this clock, never from wall-clock
time.  The clock is fixed at 2026-08-01T00:00:00Z on every boot and only ever
moves forward.
"""
import datetime as _dt

from constants import CLOCK_START

_UTC = _dt.timezone.utc


def parse_iso8601(value):
    """Parse an ISO 8601 UTC instant.  Returns a tz-aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC)
    return parsed.astimezone(_UTC)


def format_iso8601(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2)."""
    if moment is None:
        return None
    moment = moment.astimezone(_UTC)
    millis = moment.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second, millis,
    )


_current = parse_iso8601(CLOCK_START)


def now():
    """The current logical instant as a tz-aware UTC datetime."""
    return _current


def now_iso():
    return format_iso8601(_current)


def set_now(moment):
    global _current
    _current = moment.astimezone(_UTC)
    return _current


def reset():
    global _current
    _current = parse_iso8601(CLOCK_START)
    return _current


# --- calendar helpers (PRD 2.5) ---

def add_days(moment, days):
    return moment + _dt.timedelta(days=days)


def whole_day_difference(later, earlier):
    """Whole-day UTC calendar-date difference (PRD 2.5)."""
    return (later.astimezone(_UTC).date() - earlier.astimezone(_UTC).date()).days


def _days_in_month(year, month):
    if month == 12:
        return 31
    return (_dt.date(year + (month // 12), (month % 12) + 1, 1) - _dt.timedelta(days=1)).day


def add_months(moment, months):
    """Month arithmetic preserving day-of-month, clamped to the target month's
    last day when the source day does not exist there (PRD 2.5)."""
    moment = moment.astimezone(_UTC)
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, _days_in_month(year, month))
    return moment.replace(year=year, month=month, day=day)


def at_midnight(moment):
    """Normalise an instant to 00:00:00.000Z of its own UTC date."""
    moment = moment.astimezone(_UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)

"""The logical clock.

The server never reads wall-clock time.  The startup default is pinned by the
PRD (2026-09-01T00:00:00Z) and every window / expiry / scheduled-date test in
the system routes through this module.
"""

from datetime import datetime, timedelta, timezone

from errors import ERR_INVALID_REQUEST, fail

DEFAULT_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_START


def now():
    """Current logical clock instant (timezone-aware UTC)."""
    return _now


def set_now(value):
    global _now
    _now = value


def parse_iso(value):
    """Parse an ISO-8601 instant.  Accepts a trailing Z, an explicit offset,
    fractional seconds of any width, and a bare YYYY-MM-DD date."""
    if not isinstance(value, str) or not value.strip():
        fail(ERR_INVALID_REQUEST, "a timestamp value must be a non-empty string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail(ERR_INVALID_REQUEST, "timestamp %r is not a valid ISO-8601 instant" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    utc = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second,
        utc.microsecond // 1000,
    )


def now_iso():
    return fmt(_now)


def today():
    return _now.date()


def epoch_label(dt=None):
    """The YYYY-MM label of a logical-clock instant."""
    dt = dt or _now
    return "%04d-%02d" % (dt.year, dt.month)


def prior_epoch(epoch):
    """The YYYY-MM label immediately preceding `epoch`."""
    year, month = int(epoch[:4]), int(epoch[5:7])
    if month == 1:
        return "%04d-12" % (year - 1)
    return "%04d-%02d" % (year, month - 1)


def epoch_of(dt):
    if dt is None:
        return None
    return "%04d-%02d" % (dt.year, dt.month)


def months_ago(dt, months):
    return dt - timedelta(days=30 * months)

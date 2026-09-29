"""The server's logical clock (PRD section 2.4).

Before any call the clock reads exactly 2026-08-01T00:00:00Z and it never falls
back to real wall-clock time.  POST /_clock/set_current_utc moves it.
"""
from datetime import datetime, timedelta, timezone

INITIAL_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock(object):
    def __init__(self):
        self.instant = INITIAL_INSTANT

    def now(self):
        return self.instant

    def set(self, instant):
        self.instant = instant.astimezone(timezone.utc)


CLOCK = _Clock()


def now():
    """The current logical clock instant as a tz-aware UTC datetime."""
    return CLOCK.instant


def iso3(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO 8601 instant.  Returns None when the text is unparseable.

    Accepts a trailing 'Z' or an explicit offset, any number of fractional
    digits, a naive form (assumed UTC) and a bare calendar date.
    """
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_minutes(instant, minutes):
    return instant + timedelta(minutes=int(minutes))


def utc_year(instant):
    return instant.astimezone(timezone.utc).year

"""The server-side logical UTC clock (PRD §2.5).

Startup value is exactly 2026-08-01T00:00:00Z and the clock never falls back to
real wall-clock time.  Every deadline, expiry, season window, lookback and
"is this instant in the past" comparison reads this clock, and every
server-minted timestamp (created_at / updated_at / *_at) is stamped from it.
"""
import re
from datetime import datetime, timedelta, timezone, date

from constants import CLOCK_DEFAULT_ISO

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt]"
    r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, off = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        oh, om = int(off[1:3]), int(off[4:6])
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def iso(dt):
    """Render an aware datetime as an ISO-8601 UTC instant, 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


class LogicalClock(object):
    def __init__(self):
        self._now = parse_instant(CLOCK_DEFAULT_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return iso(self._now)

    def today(self):
        return self._now.date()

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)

    def reset(self):
        self._now = parse_instant(CLOCK_DEFAULT_ISO)


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def now_iso():
    return CLOCK.now_iso()


def today():
    return CLOCK.today()

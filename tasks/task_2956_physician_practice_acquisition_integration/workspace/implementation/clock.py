"""Server-controlled logical clock (PRD section 2.6).

Before the clock is ever set it reads exactly 2026-08-01T00:00:00Z, and the
server never falls back to the host's real time for any date-sensitive rule.
"""

import re
from datetime import datetime, timezone, date

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?([Zz]|[+-]00:?00)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.6)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def format_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(text):
    """Parse an ISO 8601 UTC instant; return None when malformed."""
    if not isinstance(text, str):
        return None
    m = _INSTANT_RE.match(text.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    if micro >= 1000000:
        micro = 999999
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def parse_date(text):
    """Parse a plain calendar date; return None when malformed."""
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


class LogicalClock(object):
    def __init__(self):
        self._instant = DEFAULT_INSTANT

    def reset(self):
        self._instant = DEFAULT_INSTANT

    def set(self, instant):
        self._instant = instant.astimezone(timezone.utc)

    def instant(self):
        return self._instant

    def instant_str(self):
        return format_instant(self._instant)

    def today(self):
        return self._instant.date()

    def today_str(self):
        return format_date(self._instant.date())


CLOCK = LogicalClock()


def real_now_str():
    return format_instant(datetime.now(timezone.utc))

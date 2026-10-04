# Logical clock (PRD 2.4). All date arithmetic reads this clock, never the wall clock.
from datetime import datetime, timezone, date

import constants


def _parse_iso_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' or numeric offsets. Raises ValueError on bad input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._dt = _parse_iso_datetime(constants.CLOCK_DEFAULT_ISO)
        self._raw_echo = constants.CLOCK_DEFAULT_ISO

    def set(self, to_iso8601):
        dt = _parse_iso_datetime(to_iso8601)
        self._dt = dt
        # Echo back the exact string the caller supplied (PRD 2.4 returns current_utc).
        self._raw_echo = to_iso8601

    def now(self):
        return self._dt

    def today(self):
        """UTC calendar date of the logical clock (PRD 2.4)."""
        return self._dt.date()

    def current_utc_echo(self):
        return self._raw_echo


# Module-level singleton; a fresh process re-creates it at the default.
CLOCK = LogicalClock()


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Current logical-clock instant as a 3-fractional-digit ISO string."""
    return format_ts(CLOCK.now())


def today():
    return CLOCK.today()

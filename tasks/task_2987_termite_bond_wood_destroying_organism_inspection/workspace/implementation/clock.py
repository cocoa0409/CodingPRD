"""Server side logical clock (PRD 2.5).

The mandatory startup value is exactly 2026-08-01T00:00:00Z.  The host wall
clock is never consulted, so a freshly booted process is always reproducible.
"""

from datetime import datetime, timedelta

STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, 0)


class LogicalClock(object):
    def __init__(self):
        self._now = STARTUP_UTC

    def now(self):
        """Current logical instant, tz-naive but always understood as UTC."""
        return self._now

    def set(self, instant):
        self._now = instant

    def today(self):
        """Current logical UTC calendar date."""
        return self._now.date()


clock = LogicalClock()


def days_between(earlier, later):
    """Whole days from earlier to later, floor-rounded (partial days discarded).

    Accepts datetimes or dates.  timedelta.days already floors towards minus
    infinity, which is exactly the "discard any partial day" rule of PRD 2.8.
    """
    if isinstance(earlier, datetime) or isinstance(later, datetime):
        return (_as_dt(later) - _as_dt(earlier)).days
    return (later - earlier).days


def _as_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


def plus_days(value, n):
    return value + timedelta(days=n)


def plus_hours(instant, n):
    return instant + timedelta(hours=n)

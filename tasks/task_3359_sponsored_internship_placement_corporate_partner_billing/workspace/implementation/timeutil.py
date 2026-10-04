"""The logical clock and date helpers.

The server never reads the wall clock.  It starts with the logical clock fixed
at 2026-09-01T00:00:00Z (PRD 2.6) and only a ProgramStaff clock-set request
moves it.  Every timestamp the API mints comes from this clock.
"""

import calendar
from datetime import date, datetime, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_START}


def get_clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def reset_clock():
    _clock["now"] = CLOCK_START


def now():
    """Current logical instant, used for every minted timestamp."""
    return _clock["now"]


def today():
    """The logical-clock date; every date-level comparison uses this."""
    return _clock["now"].date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant (or plain date); None when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            try:
                d = date.fromisoformat(text)
            except ValueError:
                return None
            dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(start, end):
    """Whole calendar days from start to end (inclusive periods share days)."""
    return (end.date() - start.date()).days


def add_days(dt, days):
    from datetime import timedelta

    return dt + timedelta(days=days)


def add_months(dt, months):
    """Calendar-month addition with end-of-month clamping."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_180_days(dt):
    from datetime import timedelta

    return dt + timedelta(days=180)


def age_on(dob, reference_date):
    """Completed years of age on the given date."""
    years = reference_date.year - dob.year
    if (reference_date.month, reference_date.day) < (dob.month, dob.day):
        years -= 1
    return years

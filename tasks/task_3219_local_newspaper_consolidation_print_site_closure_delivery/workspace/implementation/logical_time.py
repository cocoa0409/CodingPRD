"""Time helpers over the logical clock."""
from datetime import datetime, timedelta

from core import DB, fail


def now():
    return DB.clock.now


def today():
    return DB.clock.now.date()


def parse_hhmm(text):
    parts = str(text).split(":")
    hh = int(parts[0])
    mm = int(parts[1]) if len(parts) > 1 else 0
    return hh, mm


def deadline_dt(market, day=None):
    """The market's publication deadline as a datetime on `day`."""
    day = day or today()
    hh, mm = parse_hhmm(market.get("publication_deadline_utc") or "05:30")
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=now().tzinfo)


def cutoff_dt(route, day=None):
    """A route's dispatch cutoff as a datetime on `day`."""
    day = day or today()
    hh, mm = parse_hhmm(route.get("dispatch_cutoff_utc") or "00:00")
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=now().tzinfo)


def date_from_iso(text):
    if text is None:
        return None
    s = str(text).strip()
    if "T" in s:
        s = s.split("T", 1)[0]
    return datetime.fromisoformat(s).date()


def iso_from_date(d):
    return d.isoformat()


def ceil_to_quarter_hours(raw_hours):
    """Round a duration up to the next quarter hour."""
    quarters = int(raw_hours * 4)
    if quarters * 4 < raw_hours * 4 - 1e-9:
        quarters += 1
    if abs(quarters * 0.25 - raw_hours) > 1e-9 and quarters * 0.25 < raw_hours:
        quarters += 1
    return quarters * 0.25


def add_hours(dt, hours):
    return dt + timedelta(minutes=round(hours * 60))


def whole_minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


def days_between_floor(start, end):
    """Whole days from `start` to `end`, floored."""
    return int((end - start).total_seconds() // 86400)


def require_future_date(value, error_id):
    d = date_from_iso(value)
    if d is None or d <= today():
        fail(error_id)
    return d


def require_present(value, message):
    if value is None or value == "":
        fail("ERR_INVALID_REQUEST", message)
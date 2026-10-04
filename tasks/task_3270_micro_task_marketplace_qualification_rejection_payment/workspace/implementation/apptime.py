"""ISO-8601 UTC helpers.

Timestamps are stored and rendered as ISO 8601 UTC strings with exactly three
fractional digits (PRD §2.5). The logical clock may be set from a variety of
near-ISO inputs by the test driver, so parsing is deliberately permissive while
rendering is strict.
"""

from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def parse(value) -> datetime:
    """Parse an ISO-8601-ish instant to an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if value is None:
        raise ValueError("missing timestamp")
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt: datetime) -> str:
    """Render to ISO 8601 UTC with EXACTLY three fractional digits (PRD §2.5)."""
    dt = parse(dt)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(millis)


def now() -> str:
    """The current logical instant, always normalised to three fractional digits.

    The clock may be set from a driver-supplied string with no fractional part;
    every stamp the service writes still has to carry exactly three digits, so
    the raw clock value is normalised on the way out.
    """
    from config import clock

    return fmt(parse(clock.get()))


def now_dt() -> datetime:
    return parse(now())


def shift(value, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    return fmt(parse(value) + timedelta(days=days, hours=hours, minutes=minutes))


def add_days(value, days: int) -> str:
    return fmt(parse(value) + timedelta(days=days))


def diff_seconds(a, b) -> float:
    """a - b in seconds."""
    return (parse(a) - parse(b)).total_seconds()


def diff_days(a, b) -> float:
    """a - b in days."""
    return (parse(a) - parse(b)).total_seconds() / 86400.0
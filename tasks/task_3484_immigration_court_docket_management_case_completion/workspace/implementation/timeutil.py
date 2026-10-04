# timeutil.py — ISO 8601 parsing/formatting and weekday-date counting.
from datetime import datetime, timedelta, timezone


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or a numeric offset; naive values are read as UTC.
    Returns None when the value is not a parseable timestamp string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def count_weekday_dates(after_date, through_date):
    """Count dates D with weekday(D) in Mon..Fri and after_date < D <= through_date.

    Used by the COURT_DAYS case-age variant and the HEARING_DAY_PRORATA pace
    variant (both count Mon-Fri dates strictly after a start date up to and
    including the end date).
    """
    if through_date <= after_date:
        return 0
    n = (through_date - after_date).days
    full_weeks, rem = divmod(n, 7)
    total = full_weeks * 5
    d = after_date + timedelta(days=1)
    for i in range(rem):
        if (d + timedelta(days=i)).weekday() < 5:
            total += 1
    return total

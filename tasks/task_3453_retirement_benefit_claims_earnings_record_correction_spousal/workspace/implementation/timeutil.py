"""Calendar helpers over the three PRD granularities: YYYY-MM-DD dates,
YYYY-MM month identifiers, and ISO-8601 UTC timestamps. All arithmetic is in
whole months / days; nothing here touches wall-clock time.
"""

import re
from datetime import date, datetime, timedelta, timezone

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_month_str(s):
    """'YYYY-MM' -> (year, month) or None when malformed."""
    if not isinstance(s, str):
        return None
    m = _MONTH_RE.match(s)
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if mo < 1 or mo > 12:
        return None
    return (y, mo)


def valid_month_str(s):
    return parse_month_str(s) is not None


def parse_date_str(s):
    """'YYYY-MM-DD' -> datetime.date or None when malformed."""
    if not isinstance(s, str):
        return None
    m = _DATE_RE.match(s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_iso8601(s):
    """ISO-8601 instant -> aware datetime (UTC), or None when malformed."""
    if not isinstance(s, str):
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ym_str(ym):
    return f"{ym[0]:04d}-{ym[1]:02d}"


def month_first_day(ym):
    return date(ym[0], ym[1], 1)


def months_between_ym(a, b):
    """Whole months from month a to month b (b - a), as plain subtraction."""
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def months_between_dates(a, b):
    """Whole elapsed months from date a to date b."""
    n = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        n -= 1
    return n


def months_between_date_and_month(d, ym):
    """Whole elapsed months from date d to the first day of month ym."""
    n = (ym[0] - d.year) * 12 + (ym[1] - d.month)
    if d.day > 1:
        n -= 1
    return n


def age_months_at(birth_year, birth_month, ym):
    """Age in whole months at year-month ym (PRD §2.4)."""
    return (ym[0] - birth_year) * 12 + (ym[1] - birth_month)


def statute_deadline(tax_year):
    """(tax_year+4)-04-15 — 3 years, 3 months, 15 days after the tax year."""
    return date(tax_year + 4, 4, 15)


def plus_days(d, n):
    return d + timedelta(days=n)


def parse_iso_to_date(s):
    dt = parse_iso8601(s)
    return dt.date() if dt else None

"""Date / month arithmetic helpers.

Month arithmetic preserves the day, clamped to the target month's end
(e.g. Jan 31 + 1 month -> Feb 28/29). Whole-months-between uses the
pinned formula (y2-y1)*12 + (m2-m1) - (1 if d2.day < d1.day else 0).
"""
import re
from calendar import monthrange
from datetime import date, datetime, timezone

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_date(s):
    """Parse an ISO calendar date string -> date, or None."""
    if not isinstance(s, str):
        return None
    try:
        parts = s.split("-")
        if len(parts) != 3:
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, AttributeError):
        return None


def parse_iso_dt(s):
    """Parse an ISO 8601 datetime string -> aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def add_months(d, n):
    """date d + n months (n may be negative), day clamped to month end."""
    idx = (d.year * 12 + (d.month - 1)) + n
    y, m0 = idx // 12, idx % 12
    m = m0 + 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def whole_months_between(d1, d2):
    """Whole calendar months from d1 to d2 (pinned PRD formula)."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)


def parse_month(s):
    """Parse a strict YYYY-MM string -> (year, month), or None."""
    if not isinstance(s, str) or not MONTH_RE.match(s):
        return None
    y, m = int(s[:4]), int(s[5:7])
    if not (1 <= m <= 12):
        return None
    return (y, m)


def month_str(y, m):
    return f"{y:04d}-{m:02d}"


def next_month_str(y, m):
    return month_str(y + 1, 1) if m == 12 else month_str(y, m + 1)


def month_of_date_str(s):
    d = parse_date(s)
    return month_str(d.year, d.month) if d else None

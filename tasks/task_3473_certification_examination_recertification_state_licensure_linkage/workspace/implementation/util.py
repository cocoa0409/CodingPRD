"""Pure helpers: calendar arithmetic, parsing/formatting, rounding (PRD §2.6)."""

import calendar
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc


def parse_datetime(value):
    """Parse an ISO-8601 datetime (or date, treated as midnight UTC). Returns
    an aware UTC datetime, or None when unparseable."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.min)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            try:
                dt = datetime.combine(date.fromisoformat(s), time.min)
            except ValueError:
                return None
        else:
            iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
            try:
                dt = datetime.fromisoformat(iso)
            except ValueError:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value):
    """Parse an ISO-8601 date (or datetime, whose UTC date part is taken).
    Returns a date, or None when unparseable."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            try:
                return date.fromisoformat(s)
            except ValueError:
                return None
        dt = parse_datetime(s)
        return dt.date() if dt else None
    return None


def fmt_dt(dt):
    """ISO-8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wallclock_iso():
    return fmt_dt(datetime.now(UTC))


def _add_months_ymd(year, month, day, n):
    total = year * 12 + (month - 1) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    last = calendar.monthrange(y, m)[1]
    return y, m, min(day, last)


def add_months(dt, n):
    """Advance by n calendar months preserving day-of-month (clamped to the
    target month's last day) and time-of-day; UTC preserved (PRD §2.6)."""
    y, m, d = _add_months_ymd(dt.year, dt.month, dt.day, n)
    return dt.replace(year=y, month=m, day=d)


def add_months_date(d, n):
    y, m, dd = _add_months_ymd(d.year, d.month, d.day, n)
    return date(y, m, dd)


def add_days(dt, n):
    return dt + timedelta(days=n)


def whole_months_between(start, end):
    """Largest integer m >= 0 such that add_months(start, m) <= end."""
    if end < start:
        return 0
    # Fast bracket then refine.
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if m < 0:
        m = 0
    while add_months(start, m + 1) <= end:
        m += 1
    while m > 0 and add_months(start, m) > end:
        m -= 1
    return m


def ceil_half(x):
    """ceil(x * 0.5) as an integer number of hours (DISTRIBUTED caps)."""
    return int((Decimal(str(x)) * Decimal("0.5")).to_integral_value(rounding="ROUND_CEILING"))


def round_half_up_4dp(x):
    """Round half up to 4 decimal places; returns a float (theta_final storage)."""
    return float(Decimal(repr(float(x))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def share_cents(line_cents, bps):
    """round_half_up(line * bps / 10000) — per-line registry share (PRD §3.8)."""
    return int((Decimal(int(line_cents)) * Decimal(int(bps)) / Decimal(10000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def is_half_increment(hours):
    """True when hours is a positive multiple of 0.5 (exact, via Decimal)."""
    try:
        d = Decimal(str(hours))
    except Exception:
        return False
    if d <= 0:
        return False
    return (d * 2) == (d * 2).to_integral_value()


def num(x):
    """Emit ints for integral floats so hour totals serialize cleanly."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x

"""Time parsing/formatting, integer-checked coercion, and decimal helpers."""
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_dt(value):
    """Parse an ISO8601 string into an aware UTC datetime; None on failure."""
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


def fmt_dt(dt):
    """ISO8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def round_half_up(value):
    """Round a Decimal-compatible value half-up to the nearest integer cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    total = dt.month - 1 + months
    y = dt.year + total // 12
    m = total % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def remaining_full_months(cancel_date, end_date):
    """Full calendar months M with cancel_date <= first(M) and end_date >= first(M+1).

    Per calculations.early_termination_fee: a month M counts as full when the
    cancellation date falls on or before the first day of M and end_date falls
    on or after the first day of the following month.
    """
    count = 0
    y, m = cancel_date.year, cancel_date.month
    for _ in range(2400):  # safety bound
        first = date(y, m, 1)
        if m == 12:
            ny, nm = y + 1, 1
        else:
            ny, nm = y, m + 1
        nfirst = date(ny, nm, 1)
        if first > end_date:
            break
        if cancel_date <= first and end_date >= nfirst:
            count += 1
        y, m = ny, nm
    return count


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

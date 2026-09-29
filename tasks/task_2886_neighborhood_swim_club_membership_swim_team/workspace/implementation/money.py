"""Fiscal precision helpers (PRD §2.6).

All money is an integer number of cents.  Three rounding operators appear and
are never interchangeable:
  * round_half_up  - a value whose fractional part is exactly one half rounds
                     away from zero, to the larger magnitude.
  * ceil_div / ceil - rounding up to the next whole number (guard counts,
                     billable whole hours, swim weeks).
  * plain truncation - only where the text says so explicitly.
Durations expressed in hours as a decimal are rounded half up to 2 decimals.
"""
from decimal import Decimal, ROUND_HALF_UP


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/number half up to a whole integer (of cents)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round half up to two decimal places; returns a Decimal."""
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    """Divide and round up to the next whole number (non-negative inputs)."""
    if denominator == 0:
        return 0
    q, r = divmod(int(numerator), int(denominator))
    if r:
        q += 1
    return q


def hours_between(start_dt, end_dt):
    """Exact elapsed hours as a Decimal."""
    seconds = D((end_dt - start_dt).total_seconds())
    return seconds / D(3600)


def duration_hours_2dp(start_dt, end_dt):
    """Shift length in hours rounded half up to two decimals, as a float."""
    return float(round_half_up_2(hours_between(start_dt, end_dt)))


def ceil_hours(start_dt, end_dt):
    """Billable duration in whole hours, rounded up (PRD §3.7 step 3)."""
    minutes = int((end_dt - start_dt).total_seconds()) // 60
    if int((end_dt - start_dt).total_seconds()) % 60:
        minutes += 1
    return ceil_div(minutes, 60)


def allocate_evenly(total, count):
    """Integer quotient with the remainder handed out one each to the earliest
    positions in the given order (PRD §3.6 understaffed penalty split)."""
    if count <= 0:
        return []
    share, remainder = divmod(int(total), int(count))
    return [share + (1 if i < remainder else 0) for i in range(count)]

"""Time, rounding and identifier helpers.

Every instant in this service is rendered as an ISO 8601 UTC string with exactly
three fractional-second digits (PRD 2.4), e.g. '2026-08-01T00:00:00.000Z'.
Because all stored instants share that canonical shape, lexicographic string
comparison on them is identical to chronological comparison, which is what the
rest of the code relies on.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)

_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

EPOCH_DAY_SECONDS = 86400


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def format_instant(dt):
    """Canonical ISO 8601 UTC rendering with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.

    Returns the canonical string form, or None when the value is not a
    parseable ISO 8601 instant carrying a timezone designator.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return format_instant(base)


def to_dt(iso):
    """Turn a canonical instant string back into an aware datetime."""
    if iso is None:
        return None
    return datetime(
        int(iso[0:4]), int(iso[5:7]), int(iso[8:10]),
        int(iso[11:13]), int(iso[14:16]), int(iso[17:19]),
        int(iso[20:23]) * 1000, tzinfo=timezone.utc,
    )


def is_month_string(value):
    return isinstance(value, str) and bool(_MONTH_RE.match(value))


def month_window(period_month):
    """Half-open [first instant of the month, first instant of next month)."""
    year = int(period_month[0:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return format_instant(start), format_instant(end)


def month_start_of(iso):
    """First instant of the calendar month containing the given instant."""
    dt = to_dt(iso)
    return format_instant(datetime(dt.year, dt.month, 1, tzinfo=timezone.utc))


def month_key_of(iso):
    return iso[0:7]


def seconds_between(later_iso, earlier_iso):
    delta = to_dt(later_iso) - to_dt(earlier_iso)
    return delta.total_seconds()


def floor_div(numerator, denominator):
    """Floor division toward negative infinity."""
    if denominator == 0:
        return 0
    return numerator // denominator


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


def round_half_up_div(numerator, denominator):
    """Exact integer half-up rounding of numerator/denominator.

    Half-up means the fractional part is rounded away from zero at exactly one
    half (PRD 2.5). Implemented on integers so no floating-point residue can
    appear anywhere.
    """
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))

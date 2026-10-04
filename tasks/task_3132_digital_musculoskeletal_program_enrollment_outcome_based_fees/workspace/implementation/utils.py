"""Time, identifier and rounding helpers.

The ISO-week lattice is part of the API contract (PRD §2.4): week_index 1 begins
at Monday 2026-09-07T00:00:00Z and week N spans
[anchor + 7*(N-1) days, anchor + 7*N days) -- half-open, so an instant that sits
exactly on a week boundary belongs to the later week.
"""

import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

ANCHOR = datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)

# The logical clock's startup default (PRD §2.4).  Never falls back to real time.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

WEEK = timedelta(days=7)


def parse_iso(value):
    """Parse an ISO 8601 instant, accepting a trailing Z."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt(dt):
    """Render an instant as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt(datetime.now(timezone.utc))


def week_of(dt):
    """week_index of an instant.

    Week counting is anchored at Monday 2026-09-07T00:00:00Z, which is week_index 1
    (PRD 2.4).  Week N spans [anchor + 7*(N-1) days, anchor + 7*N days), so an
    instant that has not yet reached the anchor sits at a non-positive index: the
    logical clock's declared default of 2026-09-01 is week_index 0.  Boundary
    instants belong to the later week.
    """
    return (dt - ANCHOR) // WEEK + 1


def years_between(then, now):
    years = now.year - then.year
    if (now.month, now.day, now.hour, now.minute, now.second, now.microsecond) < (
        then.month,
        then.day,
        then.hour,
        then.minute,
        then.second,
        then.microsecond,
    ):
        years -= 1
    return years


def d(value):
    """Decimal-ise a JSON number without floating point loss."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def cents(value):
    """Round a Decimal to a whole number of cents, half up."""
    return int(d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(value):
    """Round to two decimal places, half up, as a float for JSON emission."""
    return float(d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round1(value):
    return float(d(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


_ALPHABET = string.ascii_lowercase + string.digits


def new_id():
    """A server-minted UUID with no type prefix (PRD §2.5)."""
    hexes = "0123456789abcdef"
    raw = "".join(random.choice(hexes) for _ in range(32))
    return "-".join([raw[0:8], raw[8:12], raw[12:16], raw[16:20], raw[20:32]])


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHABET + string.ascii_uppercase)
                            for _ in range(20))

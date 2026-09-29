"""Core primitives: logical clock, identifiers, timestamp formatting, decimal helpers.

PRD 2.4 -- identity and common fields.
PRD 2.5 -- the server-side logical clock (nothing reads the host wall clock for
           domain time; the wall clock is used only for meta.api_request_timestamp).
PRD 2.8 -- rounding and precision.
"""

import itertools
import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# --------------------------------------------------------------------------
# Logical clock -- PRD 2.5
# --------------------------------------------------------------------------

# "On a cold start the clock sits at exactly 2026-08-01T00:00:00Z."
DEFAULT_CLOCK_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock(object):
    def __init__(self):
        self.instant = DEFAULT_CLOCK_INSTANT


CLOCK = _Clock()

LOCK = threading.RLock()


def logical_now():
    return CLOCK.instant


def set_logical_now(instant):
    CLOCK.instant = instant


def logical_now_iso():
    return iso_instant(CLOCK.instant)


def logical_today():
    return CLOCK.instant.astimezone(timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Identifiers -- PRD 2.4: "an `id` that is a bare UUID string with no type prefix"
# --------------------------------------------------------------------------

_SEQ = itertools.count(1)


def new_id():
    """Time-ordered UUID.

    PRD 2.3 orders collections by ``created_at`` ascending with ``id`` ascending
    as the tie-break. Because ``created_at`` is taken from the *logical* clock,
    many rows share the same ``created_at``; encoding a monotonic sequence in the
    high bits makes the ``id`` tie-break resolve to creation order while keeping
    the value a syntactically valid bare UUID string.
    """
    n = next(_SEQ)
    high = "%012x" % (n & 0xFFFFFFFFFFFF)
    rnd = uuid.uuid4().hex
    return "%s-%s-7%s-8%s-%s" % (high[0:8], high[8:12], rnd[0:3], rnd[3:6], rnd[6:18])


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    """PRD 2.2: api_request_id always begins with the literal prefix ``req_``."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------
# Timestamp formatting / parsing -- PRD 2.4
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_instant(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (d.microsecond // 1000)) + "Z"


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns None when the value is not well formed.

    A date-only string is rejected: an instant must carry a time component.
    """
    if not isinstance(value, str) or isinstance(value, bool):
        return None
    text = value.strip()
    if "T" not in text and "t" not in text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a calendar date (PRD 2.4 date-only fields). Returns None if malformed."""
    if not isinstance(value, str) or isinstance(value, bool):
        return None
    if not _DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_minutes_between(start, end):
    """Whole minutes spanned, fractional minute discarded."""
    delta = (end - start).total_seconds()
    return int(Decimal(str(delta)) // Decimal("60"))


def whole_hours_between(start, end):
    """Whole hours spanned, any fractional hour discarded (PRD 3.6)."""
    delta = (end - start).total_seconds()
    return int(Decimal(str(delta)) // Decimal("3600"))


# --------------------------------------------------------------------------
# Decimal helpers -- PRD 2.8
# --------------------------------------------------------------------------


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half up to ``places`` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Money is stored as whole integer cents, rounded half up exactly once."""
    return int(round_half_up(value, 0))


def floor_int(value):
    """Capacities and ceilings always floor down (PRD 2.8)."""
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def num(value, places):
    """Emit a fixed-precision numeric value as a JSON number."""
    return float(round_half_up(value, places))

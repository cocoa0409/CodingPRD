"""Numeric, temporal and identity helpers.

Rounding conventions are pinned by PRD section 2.6:
  * "rounded half up"          -> Decimal ROUND_HALF_UP
  * a fraction of a cent on a coverage base or curtailment deduction -> floor
  * a fraction of a cent on a borrower periodic premium             -> ceil
  * four decimal place indices/ratios                               -> ROUND_HALF_UP at 4dp
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

# PRD 2.5: the logical clock starts at exactly 2026-09-01T00:00:00Z and never
# falls back to wall-clock time.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

_CLOCK = {"now": DEFAULT_CLOCK_UTC}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock value, ISO 8601 UTC with three fractional digits."""
    return fmt_utc(parse_utc(_CLOCK["now"]))


def set_clock(value_iso):
    dt = parse_utc(value_iso)
    _CLOCK["now"] = fmt_utc(dt)
    return _CLOCK["now"]


def clock_dt():
    return parse_utc(_CLOCK["now"])


# --- timestamp parsing / formatting ------------------------------------------

def parse_utc(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("not a timestamp: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_utc(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


def days(n):
    return timedelta(days=n)


def later(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def earlier(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if a <= b else b


# --- money / ratio arithmetic -------------------------------------------------

def d(value):
    return Decimal(str(value))


def floor_int(value):
    """Discard any fractional cent (PRD 2.6 "floored")."""
    return int(d(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    """Round a fractional cent up (PRD 2.6 "ceilinged")."""
    return int(d(value).to_integral_value(rounding=ROUND_CEILING))


def round_half_up_int(value):
    """Nearest whole cent, ties resolved upward (PRD 2.6 default)."""
    return int(d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    """A ratio or index carried to four decimal places, rounded half up."""
    return float(d(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def json_number(value):
    """Numbers are reported at 4dp; strip the float noise Decimal leaves behind."""
    if value is None:
        return None
    return float(value)


def months_between(start_dt, end_dt):
    """Whole-month period measured from the event instant to the filing instant."""
    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    if end_dt.day < start_dt.day:
        # the anniversary day has not been reached this month yet
        months -= 1
    if months < 0:
        months = 0
    return months


def fifth_of_month(as_of_period):
    """PRD 3.4: effective instant is the fifth calendar day at midnight UTC."""
    year, month = as_of_period.split("-")
    return datetime(int(year), int(month), 5, tzinfo=timezone.utc)
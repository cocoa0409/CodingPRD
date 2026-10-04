"""Shared primitives: identifiers, logical-clock time arithmetic, decimals.

Everything in this module is deliberately free of business rules so that the
calculation and service layers can depend on it without cycles.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The API never reads wall-clock time; this is the fixed instant the logical
# clock starts at (PRD 2.5).
DEFAULT_CLOCK = "2026-09-01T00:00:00.000Z"


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits.

    Accepts a datetime or an already-stored string, so callers never have to
    know which representation they are holding.
    """
    if isinstance(dt, str):
        dt = parse_dt(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse a client-supplied instant into a normalised UTC datetime.

    Accepts ``Z``, explicit offsets, fractional seconds, and bare local-looking
    instants (which are read as UTC).  Raises ValueError on garbage.
    """
    if value is None:
        raise ValueError("missing datetime")
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("empty datetime")
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("unsupported datetime value")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def norm_dt(value):
    """Parse and re-emit as the canonical stored representation."""
    return fmt_dt(parse_dt(value))


def dt_add_minutes(iso, minutes):
    return fmt_dt(parse_dt(iso) + timedelta(minutes=minutes))


def dt_add_hours(iso, hours):
    return fmt_dt(parse_dt(iso) + timedelta(hours=hours))


def dt_minutes_between(later_iso, earlier_iso):
    """Whole-minute (float) distance from earlier to later."""
    delta = parse_dt(later_iso) - parse_dt(earlier_iso)
    return Decimal(str(delta.total_seconds())) / Decimal(60)


def to_dec(value):
    """Coerce a JSON number/string to Decimal without binary-float drift."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise ValueError("not a number")


def rhu(value, places=0):
    """Round half up at the named decimal place."""
    quantum = Decimal(1).scaleb(-places)
    return to_dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def out_number(value):
    """Serialisation form for a weight: plain float (JSON-safe)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
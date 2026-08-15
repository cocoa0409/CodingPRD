"""Utility helpers: timestamps, UUIDs, decimal money math.

All timestamps on the wire are ISO 8601 UTC with exactly three fractional
digits and a Z suffix (PRD section 2.5). All money is integer cents; every
pinned rounding step is round-half-up (PRD section 2.8).
"""

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return f"{base}.{millis:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    if not _TS_RE.match(value.strip()):
        return None
    s = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def wall_now_ts():
    """Wall-clock UTC timestamp with millisecond precision (for meta block)."""
    return fmt_ts(datetime.now(timezone.utc))


def new_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Decimal math -- all money is integer cents, round-half-up at each pinned step
# ---------------------------------------------------------------------------

MONEY_Q = Decimal("1")


def D(x):
    """Coerce an int/str/Decimal into a Decimal exactly."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("boolean is not numeric")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise ValueError(f"not numeric: {type(x)}")


def round_half_up_cents(x):
    """Round half up to whole cents, returned as int."""
    return int(D(x).quantize(MONEY_Q, rounding=ROUND_HALF_UP))

"""Time formatting, id minting and the arithmetic primitives of PRD §2.7."""

import datetime as _dt
import random
import re
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

UTC = _dt.timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    """Server-minted UUID string with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """`req_` + 20 uppercase alphanumerics (PRD §2.2)."""
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_instant(value):
    """Parse an ISO 8601 UTC instant, truncated to millisecond resolution.

    Returns an aware datetime in UTC, or None when the value is not a valid
    ISO 8601 instant string.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _ISO_RE.match(text) is None:
        return None
    normalized = text
    if normalized.endswith("z") or normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    # millisecond resolution — all instant comparisons happen there (PRD §2.5)
    return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits, `Z` suffix."""
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        aware.year,
        aware.month,
        aware.day,
        aware.hour,
        aware.minute,
        aware.second,
        aware.microsecond // 1000,
    )


def now_real():
    """Real wall-clock instant, used for created_at/updated_at and envelope meta."""
    value = _dt.datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


# ---------------------------------------------------------------- arithmetic ---

def floor_div(numerator, denominator):
    """Exact integer floor of a non-negative rational."""
    return numerator // denominator


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) over integers -> integer.

    Exact: a value sitting on the halfway mark rounds away from zero.
    """
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def quantize(numerator, denominator, places):
    """round_half_up(numerator / denominator, places) as a Decimal."""
    exponent = Decimal(1).scaleb(-places)
    value = Decimal(numerator) / Decimal(denominator)
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def dec_places(places):
    return Decimal(1).scaleb(-places)


def num(value):
    """JSON-safe numeric: Decimal -> float, everything else untouched."""
    if isinstance(value, Decimal):
        return float(value)
    return value

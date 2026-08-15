"""Shared helpers: timestamps, pagination, common fields, constants."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from errors import invalid_request

# System constants (PRD §2.5)
ESCALATION_RATE = Decimal("0.03")
PERCENTILE_FACTOR = {
    "P50": Decimal("1.0"),
    "P62_5": Decimal("1.06"),
    "P75": Decimal("1.12"),
}
DEFAULT_MAX_OVERLAP_PCT = Decimal("0.3")
DEFAULT_MIN_PROGRESSION_PCT = Decimal("0.1")
GUIDANCE_LOW = Decimal("0.8")
GUIDANCE_HIGH = Decimal("1.2")
CAP_TIER_LOW = Decimal("1.1")
CAP_TIER_MID = Decimal("1.05")
CAP_TIER_HIGH = Decimal("1.0")
# FLSA statutory floors (server-configured constants; values per 29 USC 213 / 29 CFR 541)
FLSA_WEEKLY_MINIMUM_CENTS = 68400        # $684/week
FLSA_ANNUAL_MINIMUM_CENTS = 3556800      # $35,568/year


def now_iso() -> str:
    """System-recorded timestamps (created_at/updated_at) are stamped from the
    server-owned logical clock, never the wall clock (PRD §2.6: 'The logical
    clock stamps every system-recorded timestamp')."""
    from services import clock
    return clock.now_iso()


def round_half_up_decimal(value: Decimal, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def round4(value: Decimal) -> Decimal:
    return round_half_up_decimal(value, 4)


def round6(value: Decimal) -> Decimal:
    return round_half_up_decimal(value, 6)


def round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso_date(value, field_name: str) -> str:
    """Validate an ISO date or datetime string; return normalized string."""
    if not isinstance(value, str):
        raise invalid_request(f"{field_name} must be an ISO string")
    v = value.strip()
    try:
        if v.endswith("Z"):
            datetime.fromisoformat(v[:-1] + "+00:00")
        else:
            # date-only or naive datetime both OK per ISO 8601
            datetime.fromisoformat(v)
    except ValueError:
        raise invalid_request(f"{field_name} is not a well-formed ISO value")
    return value


def parse_int(value, field_name: str, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request(f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise invalid_request(f"{field_name} must be >= {minimum}")
    return value


def parse_non_negative_number(value, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request(f"{field_name} must be a number")
    d = Decimal(str(value))
    if d < 0:
        raise invalid_request(f"{field_name} must be non-negative")
    return d


def parse_positive_number(value, field_name: str) -> Decimal:
    d = parse_non_negative_number(value, field_name)
    if d <= 0:
        raise invalid_request(f"{field_name} must be > 0")
    return d


def require_fields(body: dict, fields):
    if body is None:
        raise invalid_request("request body required")
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request(f"missing required field: {f}")


def parse_pagination(args):
    """limit (default 10, min 1, max 100), offset (default 0, min 0)."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def sort_by_created_at(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def bump(entity: dict):
    entity["version"] += 1
    entity["updated_at"] = now_iso()

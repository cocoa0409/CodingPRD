"""Shared helpers: id/timestamp minting, mutation stamps, pagination,
payload validation, and entity serializers.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store
from errors import ERR_INVALID_REQUEST, raise_error


# ---------------------------------------------------------------------------
# Identity / time
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def touch(entity: dict):
    """Refresh updated_at and bump version by 1 on a mutable entity."""
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 0) + 1


def stamp_new(entity: dict, with_version: bool = True):
    """Stamp id, created_at, and (for versioned entities) updated_at/version."""
    entity["id"] = new_id()
    entity["created_at"] = now_ts()
    if with_version:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def D(value) -> Decimal:
    """Coerce to Decimal without going through float repr surprises."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value: Decimal, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(q, rounding=ROUND_HALF_UP)


def num2(value) -> float:
    """Round to 2dp half-up and return a JSON-friendly float."""
    return float(round_half_up(D(value), 2))


def num0(value) -> int:
    """Round to whole dollars half-up."""
    return int(round_half_up(D(value), 0))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Parse limit/offset query params using scaffold defaults (1..100 / 0)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    """Sort by created_at ascending, then apply offset/limit."""
    items_sorted = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    return items_sorted[offset:offset + limit], len(items_sorted)


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def body() -> dict:
    """Return the JSON request body, enforcing an object payload when present."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=False, silent=False)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "Malformed JSON body")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return payload


def require_fields(payload: dict, *fields: str):
    for f in fields:
        if f not in payload or payload[f] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def get_str(payload: dict, field: str, *, allow_empty: bool = False) -> str:
    v = payload.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a string")
    if not allow_empty and not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"{field} must be non-empty")
    return v


def get_int(payload: dict, field: str) -> int:
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return v


def get_num(payload: dict, field: str) -> Decimal:
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a number")
    return D(v)


def get_bool(payload: dict, field: str, default: bool = False) -> bool:
    v = payload.get(field, default)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def require_enum(payload: dict, field: str, allowed):
    v = payload.get(field)
    if v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v

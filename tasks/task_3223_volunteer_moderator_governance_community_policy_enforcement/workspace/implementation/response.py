"""Response envelope, pagination and request-shape helpers.

Envelope (§1.0 of the scaffold, §2.2 of the PRD):

    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
      "response_type": "object" | "array",
      "data": {} }

Pagination fields are `limit`, `offset`, `total_count`, `has_more`, with
defaults limit=10, min=1, max=100, offset=0 (§2.3).
"""

from datetime import datetime, timezone

import db
from errors import fail

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta(extra=None):
    meta = {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, response_type=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    return {"meta": _meta(), "response_type": response_type, "data": data}, status


def error(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def paginate(records, query):
    """Order creation-timestamp ascending, then window with limit/offset."""
    limit = query_int(query, "limit", LIMIT_DEFAULT)
    offset = query_int(query, "offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX or offset < 0:
        fail("ERR_PAGINATION_INVALID", "limit must be 1..100 and offset non-negative")
    ordered = db.sorted_created(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, meta_extra


def ok_list(records, query):
    window, meta_extra = paginate(records, query)
    payload = [to_json(r) for r in window]
    return {"meta": _meta(meta_extra), "response_type": "array", "data": payload}, 200


def to_json(record):
    """Serialize a stored record; Decimals become JSON numbers.

    Keys beginning with `_` are server-side bookkeeping and are never exposed:
    only the fields the entity table declares are part of the contract.
    """
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if hasattr(value, "quantize"):
            out[key] = float(value)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------
# Query parsing
# --------------------------------------------------------------------------
def query_int(query, name, default):
    raw = query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        if name in ("limit", "offset"):
            fail("ERR_PAGINATION_INVALID", f"{name} must be an integer")
        fail("ERR_INVALID_REQUEST", f"{name} must be an integer")


def query_str(query, name):
    raw = query.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_int_filter(query, name):
    raw = query.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", f"{name} must be an integer")


def filter_enum(records, key, value, allowed):
    if value is None:
        return records
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", f"unknown {key} filter value")
    return [r for r in records if r.get(key) == value]


def filter_int(records, key, value, low, high):
    if value is None:
        return records
    if value < low or value > high:
        fail("ERR_INVALID_REQUEST", f"{key} filter out of range")
    return [r for r in records if r.get(key) == value]


# --------------------------------------------------------------------------
# Request body validation (§2.6 request-shape band)
# --------------------------------------------------------------------------
def body(request):
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def required(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", f"{name} is required")
    value = data[name]
    if isinstance(value, str) and value.strip() == "":
        fail("ERR_INVALID_REQUEST", f"{name} is required")
    return value


def optional(data, name, default=None):
    value = data.get(name)
    return default if value is None else value


def as_str(data, name, required_=True, default=None):
    if name not in data or data[name] is None:
        if required_:
            fail("ERR_INVALID_REQUEST", f"{name} is required")
        return default
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", f"{name} must be a non-empty string")
    return value


def as_int(data, name, required_=True, default=None, low=None, high=None):
    if name not in data or data[name] is None:
        if required_:
            fail("ERR_INVALID_REQUEST", f"{name} is required")
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            fail("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if low is not None and value < low:
        fail("ERR_INVALID_REQUEST", f"{name} is out of range")
    if high is not None and value > high:
        fail("ERR_INVALID_REQUEST", f"{name} is out of range")
    return value


def as_bool(data, name, required_=False, default=False):
    if name not in data or data[name] is None:
        if required_:
            fail("ERR_INVALID_REQUEST", f"{name} is required")
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", f"{name} must be a boolean")
    return value


def as_num(data, name, required_=True, default=None, low=None, high=None):
    if name not in data or data[name] is None:
        if required_:
            fail("ERR_INVALID_REQUEST", f"{name} is required")
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", f"{name} must be a number")
    value = float(value)
    if low is not None and value < low:
        fail("ERR_INVALID_REQUEST", f"{name} is out of range")
    if high is not None and value > high:
        fail("ERR_INVALID_REQUEST", f"{name} is out of range")
    return value


def as_enum(data, name, allowed, required_=True, default=None):
    if name not in data or data[name] is None:
        if required_:
            fail("ERR_INVALID_REQUEST", f"{name} is required")
        return default
    value = data[name]
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", f"{name} is not a recognised value")
    return value


def as_list(data, name, required_=True, default=None):
    if name not in data or data[name] is None:
        if required_:
            fail("ERR_INVALID_REQUEST", f"{name} is required")
        return default
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", f"{name} must be an array")
    return value
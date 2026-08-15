"""Request body and query parameter validation helpers (PRD §2.6 priority 18)."""
import math

from flask import request

from errors import bad_request
from timeutil import parse_dt


def body():
    """Parse the JSON request body; malformed JSON or non-object -> 400."""
    if not request.data:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        raise bad_request("Request body must be valid JSON")
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object")
    return parsed


def req(b, name):
    """Required field presence (null counts as missing)."""
    if name not in b or b[name] is None:
        raise bad_request(f"Missing required field: {name}")
    return b[name]


def as_str(v, name):
    if not isinstance(v, str) or v.strip() == "":
        raise bad_request(f"Field '{name}' must be a non-empty string")
    return v


def as_int(v, name, min_v=None, max_v=None):
    if not isinstance(v, int) or isinstance(v, bool):
        raise bad_request(f"Field '{name}' must be an integer")
    if min_v is not None and v < min_v:
        raise bad_request(f"Field '{name}' must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise bad_request(f"Field '{name}' must be <= {max_v}")
    return v


def as_num(v, name, min_v=None, max_v=None, min_exclusive=False):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        raise bad_request(f"Field '{name}' must be a finite number")
    if min_v is not None:
        if min_exclusive and not v > min_v:
            raise bad_request(f"Field '{name}' must be > {min_v}")
        if not min_exclusive and not v >= min_v:
            raise bad_request(f"Field '{name}' must be >= {min_v}")
    if max_v is not None and not v <= max_v:
        raise bad_request(f"Field '{name}' must be <= {max_v}")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise bad_request(f"Field '{name}' must be a boolean")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise bad_request(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def as_dt(v, name):
    return parse_dt(v, name)


def pagination():
    """limit/offset query params: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total

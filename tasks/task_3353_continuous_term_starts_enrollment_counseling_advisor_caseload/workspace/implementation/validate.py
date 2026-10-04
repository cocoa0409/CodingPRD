"""Request-shape validation helpers (priority 3) and pagination parsing."""

from flask import request

from errors import raise_err
from store import parse_date, parse_datetime


def get_body():
    """Return the JSON request body as a dict; absent/invalid body -> {}.
    Callers that require fields will catch that via req_* helpers."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be an integer" % field)
    return v


def opt_int(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not is_int(v):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be an integer" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be a boolean" % field)
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(
            "ERR_INVALID_REQUEST",
            "field '%s' is required and must be one of %s" % (field, sorted(allowed)),
        )
    return v


def req_date(body, field):
    """Required ISO date string; returns (raw, parsed_date)."""
    raw = body.get(field)
    if not isinstance(raw, str) or raw == "":
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be an ISO date string" % field)
    try:
        return raw, parse_date(raw)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "field '%s' is not a valid ISO date" % field)


def opt_date(body, field, default=None):
    raw = body.get(field, default)
    if raw is None:
        return None, None
    if not isinstance(raw, str) or raw == "":
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be an ISO date string" % field)
    try:
        return raw, parse_date(raw)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "field '%s' is not a valid ISO date" % field)


def req_timestamp(body, field):
    raw = body.get(field)
    if not isinstance(raw, str) or raw == "":
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be an ISO 8601 timestamp" % field)
    try:
        return raw, parse_datetime(raw)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "field '%s' is not a valid ISO 8601 timestamp" % field)


def pagination_args():
    """limit: default 10, bounded [1, 100]; offset: default 0, bounded >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items):
    """items: full sorted list. Returns (page_items, limit, offset, total)."""
    limit, offset = pagination_args()
    total = len(items)
    return items[offset:offset + limit], limit, offset, total

"""Request body and query validation helpers.

Malformed bodies, wrong types, non-positive amounts where positive ones are
required, and unrecognized enum values all yield ERR_INVALID_REQUEST (400).
"""
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def body_json(required=False):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Request body must be valid JSON", 400)
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _bad(field, detail):
    return ApiError(ERR_INVALID_REQUEST, "%s %s" % (field, detail), 400)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise _bad(field, "is required and must be a non-empty string")
    return v


def req_int(data, field, min_value=None):
    v = data.get(field)
    if not _is_int(v):
        raise _bad(field, "is required and must be an integer")
    if min_value is not None and v < min_value:
        raise _bad(field, "must be >= %d" % min_value)
    return v


def opt_int(data, field, default=None, min_value=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_int(v):
        raise _bad(field, "must be an integer")
    if min_value is not None and v < min_value:
        raise _bad(field, "must be >= %d" % min_value)
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise _bad(field, "is required and must be a boolean")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise _bad(field, "must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return v


def parse_dt(value, field):
    if not isinstance(value, str):
        raise _bad(field, "must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise _bad(field, "must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(data, field):
    return parse_dt(data.get(field), field)


def page_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset

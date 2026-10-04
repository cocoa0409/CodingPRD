"""Response envelope (PRD §2.2), pagination (§2.3), and body validation helpers."""

import secrets
import string

from flask import jsonify, request

import clock
from errors import validation

_ALNUM = string.ascii_letters + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def gen_request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": clock.iso_ms(clock.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise validation("request body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise validation("%s is required" % field)
    return data[field]


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation("%s must be an integer" % field)
    return value


def as_str(value, field):
    if not isinstance(value, str) or not value:
        raise validation("%s must be a non-empty string" % field)
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise validation("%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def as_list(value, field):
    if not isinstance(value, list):
        raise validation("%s must be an array" % field)
    return value


def opt_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return as_int(data[field], field)


def req_int(data, field):
    return as_int(require(data, field), field)


def req_str(data, field):
    return as_str(require(data, field), field)


def req_enum(data, field, allowed):
    return as_enum(require(data, field), field, allowed)


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise validation("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise validation("offset must be an integer")
    # PRD §2.3 bounds: min 1, max 100, offset default 0 — clamp rather than reject
    limit = min(max(limit, MIN_LIMIT), MAX_LIMIT)
    offset = max(offset, DEFAULT_OFFSET)
    return limit, offset


def paginate(items):
    """Sort by creation ascending (insertion order breaks same-clock ties),
    then apply limit/offset. Returns (page, total_count, limit, offset)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = get_pagination()
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset

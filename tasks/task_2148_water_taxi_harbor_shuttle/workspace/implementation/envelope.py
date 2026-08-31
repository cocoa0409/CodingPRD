"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from store import request_id, iso_ms

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination():
    """Returns (limit, offset); raises ERR_INVALID_REQUEST when out of bounds."""
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def enum_param(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a declared value." % name)
    return raw


def str_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw

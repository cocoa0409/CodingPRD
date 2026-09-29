"""Response envelope helpers (PRD §2.2, §2.3)."""

from flask import jsonify, request

from db import new_request_id, now_iso, ordered, public
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    raw = raw.strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s may not be larger than %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(rows, serialiser=None):
    """Order, window and wrap a collection of rows."""
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    serialise = serialiser or public
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": [serialise(r) for r in window],
    }
    body["meta"]["limit"] = limit
    body["meta"]["offset"] = offset
    body["meta"]["total_count"] = total
    body["meta"]["has_more"] = (offset + len(window)) < total
    return jsonify(body), 200

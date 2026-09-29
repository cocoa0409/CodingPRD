"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

import store
from errors import ApiError

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.iso(store.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)


def pagination():
    """Parse and bounds-check limit/offset for the eight paginated collections."""
    limit = _int_param("limit", DEFAULT_LIMIT)
    offset = _int_param("offset", DEFAULT_OFFSET)
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be zero or greater.")
    return limit, offset


def paginated(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def nested_list(rows, serializer):
    """Nested listings take no query parameters and are never bounds-checked."""
    items = [serializer(r) for r in rows]
    return ok_list(items, len(items), 0, len(items))

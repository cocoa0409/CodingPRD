"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

from db import clock, iso, new_request_id
from errors import ERR_INVALID_REQUEST, ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(clock.now),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    meta = dict(pagination) if pagination else None
    body = {
        "meta": _meta(meta),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso(clock.now),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Query parameter %s must be an integer" % name)


def pagination_params():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT)
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET)
    if offset < 0:
        offset = 0
    return limit, offset


def paged(items, sort_key=None):
    """Apply §2.3: ascending created_at, then limit/offset."""
    if sort_key is None:
        sort_key = lambda row: (row.get("created_at") or "", row.get("_seq", 0))
    ordered = sorted(items, key=sort_key)
    limit, offset = pagination_params()
    total_count = len(ordered)
    window = ordered[offset:offset + limit]
    has_more = (offset + limit) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return window, pagination
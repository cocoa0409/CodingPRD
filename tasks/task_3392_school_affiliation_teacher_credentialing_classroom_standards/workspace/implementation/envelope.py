"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import uuid

from flask import jsonify, request

from errors import ApiError, ERR_VALIDATION
from store import now_iso


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


def pagination_params():
    """limit: default 10, clamped to [1, 100]; offset: default 0, min 0."""
    args = request.args

    def _int(name, default):
        v = args.get(name)
        if v is None:
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "Query parameter %r must be an integer." % name)

    limit = _int("limit", 10)
    offset = _int("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list and build the meta pagination block."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def list_response(items, limit, offset, serializer):
    page, meta = paginate(items, limit, offset)
    return ok([serializer(x) for x in page], 200, pagination=meta)

"""Standard response envelope (PRD 2.2) and pagination helpers (PRD 2.3)."""

from flask import jsonify

from db import fmt, clock_now, mint_request_id
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta(pagination=None):
    meta = {
        "api_request_id": mint_request_id(),
        "api_request_timestamp": fmt(clock_now()),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def object_response(data, http_status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), http_status


def array_response(items, pagination):
    return jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}), 200


def error_response(error):
    if isinstance(error, ApiError):
        error_id = error.error_id
        message = error.message
        status = error.http_status
    else:
        error_id = "ERR_INVALID_REQUEST"
        message = "The request is malformed or carries an unacceptable value."
        status = 400
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status


def parse_pagination(args):
    """`limit` 1..100 defaulting to 10, `offset` defaulting to 0 (PRD 2.3)."""
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    if raw_limit is None or raw_limit == "":
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer row count.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is None or raw_offset == "":
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer row count.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset cannot be honoured as a row count.")
    return limit, offset


def paginate(rows, args):
    limit, offset = parse_pagination(args)
    total = len(rows)
    window = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return window, pagination
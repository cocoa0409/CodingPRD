"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from util import fmt_instant, now_wall

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(now_wall()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination():
    """limit/offset from the query string, validated per PRD 2.3."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_value < PAGINATION_MIN_LIMIT or limit_value > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None or offset == "":
        offset_value = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_value < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit_value, offset_value


def paginated(rows, serializer):
    """Render an ordered row list as a paginated array response."""
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), 200

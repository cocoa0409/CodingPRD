"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import fmt_ts, store
from datetime import datetime, timezone

ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def page_params():
    """Parse and validate `limit` / `offset` query parameters."""
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None or limit == "":
        limit_v = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit_v = int(str(limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < PAGE_LIMIT_MIN or limit_v > PAGE_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )
    if offset is None or offset == "":
        offset_v = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset_v = int(str(offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater")
    return limit_v, offset_v


def ok_list(rows, serializer):
    """Paginated list response; rows must already be sorted and scoped."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }
    return jsonify(body), 200

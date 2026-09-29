"""Response envelope helpers (PRD section 2.2) and pagination (PRD section 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import iso_ts, store

ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ts(store.now()),
    }


def success(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination():
    """Parse limit/offset query parameters, honouring the PRD defaults and bounds."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginated(items, serializer):
    """Return a list envelope: pagination fields live inside meta."""
    limit, offset = read_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(item) for item in page],
    }
    return jsonify(body), 200

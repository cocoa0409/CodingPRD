"""Standard response envelope and pagination, exactly as PRD 2.2 and 2.3."""
from flask import jsonify, request

from common import fmt_dt, new_request_id, utc_now
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(utc_now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _parse_page_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = str(raw).strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %d." % (name, maximum))
    return value


def read_pagination():
    limit = _parse_page_param(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _parse_page_param("offset", PAGINATION_DEFAULT_OFFSET, PAGINATION_MIN_OFFSET, None)
    return limit, offset


def paginated(rows, serializer):
    """Apply the page window and emit the array envelope."""
    limit, offset = read_pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in window],
    }
    return jsonify(body), 200

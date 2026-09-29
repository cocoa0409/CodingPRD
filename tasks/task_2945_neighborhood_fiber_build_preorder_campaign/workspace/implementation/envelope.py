"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import fmt_dt, now

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": fmt_dt(now())}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def array(items):
    """An array response with no pagination block (non-list endpoints)."""
    body = {"meta": _meta(), "response_type": "array", "data": list(items)}
    return jsonify(body), 200


def paginated(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": list(items)}
    return jsonify(body), 200


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body)


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST", "%s out of range" % name)
    return value


def page_params():
    """Effective (limit, offset), rejecting out-of-range values with 400."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def page(items, limit, offset):
    return items[offset: offset + limit]


def list_response(items, serializer):
    limit, offset = page_params()
    total = len(items)
    window = page(items, limit, offset)
    return paginated([serializer(r) for r in window], total, limit, offset)

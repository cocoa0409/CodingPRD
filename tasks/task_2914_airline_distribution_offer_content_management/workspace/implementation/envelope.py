"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import iso, now

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(now())}


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not (text.lstrip("+-").isdigit()):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is above its maximum." % name)
    return value


def pagination():
    """Returns (limit, offset), validated per PRD 2.3."""
    limit = _query_int("limit", PAGINATION_LIMIT_DEFAULT,
                       PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _query_int("offset", PAGINATION_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total

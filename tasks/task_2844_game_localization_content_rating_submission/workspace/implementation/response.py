"""Response envelope, pagination and list ordering (PRD SS2.2 / SS2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import fmt_instant
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    moment = datetime.now(timezone.utc)
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_instant(moment),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def sort_rows(rows, natural_key):
    """created_at ascending, ties broken by the entity's natural key ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], natural_key(r)))


def paginated(rows, serializer, natural_key):
    limit, offset = pagination()
    ordered = sort_rows(rows, natural_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
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

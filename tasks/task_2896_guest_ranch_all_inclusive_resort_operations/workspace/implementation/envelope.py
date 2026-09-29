"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import datetime
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import fmt_instant

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
        "api_request_timestamp": fmt_instant(
            datetime.datetime.now(datetime.timezone.utc)
        ),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        if text != str(int(text)):
            raise ValueError(text)
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "%s must be <= %s." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def listing(rows, serializer):
    """Sort-stable, paginated array response."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in page],
    }
    return jsonify(body), 200

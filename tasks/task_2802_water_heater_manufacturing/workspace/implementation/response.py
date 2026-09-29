"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.fmt_ts(db.db.now()),
    }


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name
        )
    if value < minimum:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be at least %d." % (name, minimum),
        )
    if maximum is not None and value > maximum:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be at most %d." % (name, maximum),
        )
    return value


def pagination():
    """Returns the effective (limit, offset) pair, validating the declared bounds."""
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def paginate(rows, serializer):
    """Apply pagination to an already-ordered row list and emit a list envelope."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)

"""Response envelope helpers (PRD section 2.2 and 2.3)."""

import random
import string

from flask import jsonify, request

import clock
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt_instant(clock.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


def _int_arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION")


def pagination():
    limit = _int_arg("limit")
    offset = _int_arg("offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def page(rows, serializer=None):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    if serializer is None:
        import store
        serializer = store.public
    return collection([serializer(r) for r in window], limit, offset, total)

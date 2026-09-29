"""The response envelope of PRD 2.2 and the pagination rules of PRD 2.3."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import iso, now

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": iso(now())}


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {} if data is None else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    negative = raw.startswith("-")
    digits = raw[1:] if negative or raw.startswith("+") else raw
    if not digits.isdigit():
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_VALIDATION", "%s is out of bounds." % name)
    return value


def page_params():
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)

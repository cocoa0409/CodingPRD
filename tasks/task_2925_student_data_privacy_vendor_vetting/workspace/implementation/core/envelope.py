"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from . import store
from .errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": store.fmt_dt(store.wall_now()),
    }


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def created(data):
    return ok(data, 201)


def err(error_id, message, code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), code


PAGINATION_KEYS = ("limit", "offset")


def paged(rows, serializer):
    """Resolve limit/offset, slice, and build the array envelope."""
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    total = len(rows)
    page = rows[offset: offset + limit]
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


def _int_param(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if lo is not None and value < lo:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, lo))
    if hi is not None and value > hi:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %d." % (name, hi))
    return value


def query_filters(allowed):
    """Validate the query string of a list endpoint and return the given filters.

    `allowed` maps a filter name to either None (free string) or a set of legal
    enum members.  Unknown query parameters are an unknown field (PRD 2.5).
    """
    out = {}
    for key in request.args.keys():
        if key in PAGINATION_KEYS:
            continue
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown query parameter '%s'." % key)
    for key, members in allowed.items():
        raw = request.args.get(key)
        if raw is None:
            continue
        if members is not None and raw not in members:
            raise ApiError("ERR_INVALID_REQUEST", "Invalid value for filter '%s'." % key)
        out[key] = raw
    return out

"""Standard response envelope (PRD section 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

import store
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _parse_int_param(raw):
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        raise ValueError("empty")
    if raw.startswith("+"):
        raw = raw[1:]
    neg = raw.startswith("-")
    digits = raw[1:] if neg else raw
    if not digits.isdigit():
        raise ValueError("not an integer")
    value = int(raw)
    return value


def pagination():
    """PRD 2.3 / ladder rung 6.  Returns (limit, offset)."""
    try:
        limit = _parse_int_param(request.args.get("limit"))
        offset = _parse_int_param(request.args.get("offset"))
    except ValueError:
        raise ApiError("ERR_INVALID_PAGINATION")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)

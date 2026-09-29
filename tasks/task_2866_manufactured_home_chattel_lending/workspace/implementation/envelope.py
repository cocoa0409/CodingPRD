"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

import core
from errors import ApiError


def _meta():
    return {
        "api_request_id": core.new_request_id(),
        "api_request_timestamp": core.iso(core.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
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


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        if text != str(int(text)):
            raise ValueError(text)
        return int(text)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT)
    offset = _query_int("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)

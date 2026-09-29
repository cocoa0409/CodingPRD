"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify

import clock
import errors
import util

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": clock.now(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _read_int_param(args, name, default, minimum, maximum):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not (text.lstrip("+-").isdigit() and text.lstrip("+-") != ""):
        raise errors.ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if value < minimum:
        raise errors.ApiError("ERR_INVALID_REQUEST", "%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise errors.ApiError("ERR_INVALID_REQUEST", "%s is above its maximum." % name)
    return value


def pagination(args):
    limit = _read_int_param(
        args, "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _read_int_param(args, "offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset: offset + limit]


def listing(rows, args, serializer):
    """Apply pagination to already-filtered, already-ordered rows."""
    limit, offset = pagination(args)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, total)

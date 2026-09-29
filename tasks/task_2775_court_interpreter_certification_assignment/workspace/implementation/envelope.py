"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify

from errors import ApiError
from store import now
from util import fmt_dt, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    """`limit` (default 10, 1..100) and `offset` (default 0, >= 0)."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        limit = _positive_int(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        offset = _positive_int(raw_offset, "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _positive_int(raw, field):
    text = str(raw).strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    value = int(digits)
    return -value if negative else value


def paginate(rows, limit, offset):
    """Slice an already-ordered row list; `total_count` is the pre-slice size."""
    total = len(rows)
    return rows[offset:offset + limit], total

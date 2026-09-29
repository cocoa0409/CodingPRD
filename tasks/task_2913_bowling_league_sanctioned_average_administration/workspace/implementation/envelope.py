"""Response envelope of PRD 2.2 and the pagination window of PRD 2.3."""

import random
import string

from flask import jsonify, request

from clock import clock
from errors import ApiError

ALNUM = string.ascii_uppercase + string.digits


def _meta():
    suffix = "".join(random.choice(ALNUM) for _ in range(20))
    return {
        "api_request_id": "req_" + suffix,
        "api_request_timestamp": clock.iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def page_params():
    """Read and validate limit/offset (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def window(rows, limit, offset, serializer):
    total = len(rows)
    chunk = rows[offset:offset + limit]
    return listing([serializer(r) for r in chunk], limit, offset, total)

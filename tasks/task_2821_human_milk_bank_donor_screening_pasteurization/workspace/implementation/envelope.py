"""PRD 2.2 response envelope and PRD 2.3 pagination.

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""

import json

from flask import Response, request

from errors import invalid
from util import fmt_instant, new_request_id, now_wall

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_instant(now_wall()),
    }


def _respond(payload, status):
    body = json.dumps(payload, allow_nan=False)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    """Single-resource (or empty) 2xx response."""
    return _respond(
        {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}},
        status,
    )


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _respond({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    return _respond(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )


def pagination():
    """Read `limit`/`offset` from the query string with PRD 2.3 bounds."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            invalid("limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer.")
        if offset < 0:
            invalid("offset may not be negative.")
    return limit, offset


def page(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)

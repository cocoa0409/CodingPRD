"""Response envelope helpers (PRD §2.2, §2.3).

Success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
           total_count, has_more]}, "response_type": "object"|"array",
           "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""

import uuid

from flask import jsonify, request

import clock
from errors import fail


def _request_id():
    # Server-generated unique id starting with "req_" (alphanumeric suffix).
    return "req_" + uuid.uuid4().hex


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


def _parse_nonnegative_int(raw, field):
    try:
        value = int(raw, 10)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", f"query parameter '{field}' must be an integer")
    return value


def paginate(records):
    """Apply limit/offset per PRD §2.3 (defaults 10/0, limit range 1..100).

    `records` must already be sorted (created_at ascending). Returns
    (page, pagination_meta).
    """
    args = request.args
    if "limit" in args:
        limit = _parse_nonnegative_int(args.get("limit"), "limit")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    else:
        limit = 10
    if "offset" in args:
        offset = _parse_nonnegative_int(args.get("offset"), "offset")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    else:
        offset = 0
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_created(records):
    """Default list ordering: created_at ascending (PRD §2.3). Ties (common
    under the logical clock) break by insertion sequence, never by id."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))

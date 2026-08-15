"""Response envelope helpers implementing PRD section 2.2 and 2.3 verbatim."""

import uuid

from flask import jsonify

import store
from timeutil import fmt_dt

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt(store.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    """limit/offset query parameters with defaults and clamping (PRD 2.3)."""
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = PAGINATION_LIMIT_DEFAULT
        if limit < PAGINATION_LIMIT_MIN:
            limit = PAGINATION_LIMIT_MIN
        if limit > PAGINATION_LIMIT_MAX:
            limit = PAGINATION_LIMIT_MAX
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = PAGINATION_OFFSET_DEFAULT
        if offset < PAGINATION_OFFSET_DEFAULT:
            offset = PAGINATION_OFFSET_DEFAULT
    return limit, offset


def paginate(rows, args):
    limit, offset = read_pagination(args)
    total = len(rows)
    window = rows[offset: offset + limit]
    return window, limit, offset, total


def list_response(all_rows, args, serializer):
    rows = sorted(all_rows, key=lambda r: (r["created_at"], r["_seq"]))
    window, limit, offset, total = paginate(rows, args)
    return array_response([serializer(r) for r in window], limit, offset, total)

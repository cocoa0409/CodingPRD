"""Standard success / error response envelopes (PRD section 2.2, 2.3)."""

from flask import jsonify

import store
from errors import ApiError

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.fmt_instant(store.wall_now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": store.public(data)}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty():
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), 200


def ok_null():
    """A 200 whose declared output payload is null."""
    body = {"meta": _meta(), "response_type": "object", "data": None}
    return jsonify(body), 200


def array(rows, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": [store.public(r) for r in rows],
    }
    return jsonify(body), status


def page(rows, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [store.public(r) for r in window],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_args(args):
    """limit defaults to 10 and lies in [1, 100]; offset defaults to 0."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be at least 1 and at most 100.",
            )
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset

"""Standard response envelope helpers (scaffold 1.0 / PRD 2.2, 2.3)."""

import secrets
import string

from flask import jsonify

import db

_PAGE_DEFAULT_LIMIT = 10
_PAGE_MIN_LIMIT = 1
_PAGE_MAX_LIMIT = 100
_PAGE_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits)
                            for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.format_ts(db.now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def parse_pagination(args):
    """limit/offset query params (PRD 2.3): default 10/0, clamp to
    [1,100] / [0,inf). Non-integer input fails as ERR_INVALID_REQUEST."""
    from errors import invalid

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = _PAGE_DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise invalid("limit must be an integer")
    try:
        offset = _PAGE_DEFAULT_OFFSET if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise invalid("offset must be an integer")
    limit = max(_PAGE_MIN_LIMIT, min(_PAGE_MAX_LIMIT, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows, args):
    """Slice an already-ordered list; returns (ok_list response)."""
    limit, offset = parse_pagination(args)
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, total, limit, offset)


def sort_by_created(rows):
    """Default list order: created_at ascending (PRD 2.3). Stable sort keeps
    insertion order for equal timestamps."""
    return sorted(rows, key=lambda r: r["created_at"])

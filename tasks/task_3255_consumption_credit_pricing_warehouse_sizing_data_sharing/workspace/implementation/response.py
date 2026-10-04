"""Response envelope + pagination helpers (PRD §2.2, §2.3)."""
from flask import jsonify, request

from errors import err
from util import iso_now, req_id


def _meta(extra=None):
    meta = {"api_request_id": req_id(), "api_request_timestamp": iso_now()}
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    return jsonify(body), status


def paged(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    body = {
        "meta": _meta({"limit": limit, "offset": offset,
                       "total_count": total, "has_more": has_more}),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def paged_cursor(items, limit, total, has_more, next_cursor, offset=0):
    # PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    # `total_count`, `has_more`) are included for list endpoints." The drawdown
    # collection deviates only in that its page is addressed by `cursor` rather
    # than by `offset`; the envelope still reports the offset it served.
    body = {
        "meta": _meta({"limit": limit, "offset": offset, "total_count": total,
                       "has_more": has_more, "next_cursor": next_cursor}),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


# ------------------------------------------------------------ pagination ----

def pagination():
    """Read limit/offset from the query string with PRD defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = 10 if raw_limit in (None, "") else int(raw_limit)
        offset = 0 if raw_offset in (None, "") else int(raw_offset)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit and offset must be integers.")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be non-negative.")
    return limit, offset


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))

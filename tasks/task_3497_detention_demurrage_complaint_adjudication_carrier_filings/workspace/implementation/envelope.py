"""Response envelope (SCAFFOLD §1.0 / PRD §2.2-§2.3) and pagination."""
import uuid

from flask import jsonify, request

from clock import CLOCK
from errors import fail, ERR_INVALID_REQUEST

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": CLOCK.render_precise(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _parse_page_int(raw, name, lo, hi):
    try:
        v = int(raw)
    except (TypeError, ValueError):
        fail(ERR_INVALID_REQUEST, "query parameter %r must be an integer" % name)
    if v < lo or v > hi:
        fail(ERR_INVALID_REQUEST,
             "query parameter %r out of range [%d, %d]" % (name, lo, hi))
    return v


def paginate(records):
    """Sort by creation order (created_at asc; _seq tiebreak under a frozen
    clock) and slice per limit/offset query params."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        limit = _parse_page_int(raw_limit, "limit", PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    if raw_offset is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        offset = _parse_page_int(raw_offset, "offset", 0, 1 << 62)
    items = sorted(records, key=lambda r: r["_seq"])
    total = len(items)
    return items[offset:offset + limit], limit, offset, total

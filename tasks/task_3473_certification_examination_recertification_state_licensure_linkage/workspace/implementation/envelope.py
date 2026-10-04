"""Response envelope helpers (PRD §2.2, §2.3)."""

import uuid

from flask import jsonify, request

from util import wallclock_iso
from errors import ApiError


def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def meta_block(pagination=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": wallclock_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok_object(data, code=200):
    return jsonify({"meta": meta_block(), "response_type": "object", "data": data}), code


def ok_list(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return jsonify({"meta": meta_block(pagination), "response_type": "array", "data": items}), 200


def error_body(err):
    return jsonify({
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


def paginate_params():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_page(all_items):
    """Sort by (created_at, insertion seq) ascending and slice one page."""
    limit, offset = paginate_params()
    ordered = sorted(all_items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset

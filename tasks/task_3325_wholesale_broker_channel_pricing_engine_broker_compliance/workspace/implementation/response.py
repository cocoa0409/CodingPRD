"""Response envelope construction (PRD 2.2 / 2.3)."""

from flask import jsonify

import db
from constants import DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT


def _meta(request_id, timestamp):
    return {"api_request_id": request_id, "api_request_timestamp": timestamp}


def success_object(payload):
    body = {
        "meta": _meta(db.new_request_id(), db.now_iso()),
        "response_type": "object",
        "data": payload if payload is not None else {},
    }
    return jsonify(body)


def success_array(items, total_count, limit, offset):
    meta = _meta(db.new_request_id(), db.now_iso())
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body)


def paged_object(payload, limit, offset, total_count):
    """A non-list read (e.g. the closing pipeline) that still carries the
    pagination block in meta (PRD 2.3)."""
    meta = _meta(db.new_request_id(), db.now_iso())
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return jsonify({
        "meta": meta,
        "response_type": "object",
        "data": payload,
    })


def resolved_paged_object(payload, limit, offset, total_count):
    return paged_object(payload, limit, offset, total_count)


def error_body(error_id, message):
    return {
        "meta": _meta(db.new_request_id(), db.now_iso()),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, http_status):
    return jsonify(error_body(error_id, message)), http_status


def resolve_pagination(args):
    """Read limit/offset exactly as PRD 2.3 defines them."""
    limit = _int_param(args.get("limit"), DEFAULT_LIMIT)
    offset = _int_param(args.get("offset"), 0)
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def _int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def paginate(rows, limit, offset):
    """Sort by creation timestamp ascending, then apply the window."""
    ordered = sorted(rows, key=lambda row: (row.get("created_at") or "", row.get("id") or ""))
    return ordered[offset:offset + limit], len(ordered)
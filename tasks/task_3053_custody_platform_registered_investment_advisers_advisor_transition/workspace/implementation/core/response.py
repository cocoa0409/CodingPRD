"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""

from flask import jsonify

from core.store import STORE, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": STORE.clock.now(),
    }


def ok(data, status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, params):
    """Apply the scaffold's limit/offset contract and return (page, meta)."""
    limit = params.limit
    offset = params.offset
    total = len(rows)
    page = rows[offset:offset + limit] if limit else []
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
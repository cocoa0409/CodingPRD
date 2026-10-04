"""Response envelope helpers matching §1.0 / PRD §2.2 verbatim."""

from flask import jsonify

from utils import iso_z, new_request_id, clock_now


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_z(clock_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(payload, status=200, is_list=False, page=None):
    meta = _meta(page)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": payload if payload is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page_meta(items, limit, offset):
    return {
        "limit": limit,
        "offset": offset,
        "total_count": len(items),
        "has_more": offset + limit < len(items),
    }


def paginate(items, limit, offset):
    return items[offset:offset + limit]
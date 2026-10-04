"""Standard response envelope helpers (PRD section 2.2)."""
from flask import jsonify

import core


def _meta_base():
    return {
        "api_request_id": core.request_id(),
        "api_request_timestamp": core.fmt_dt(core.wall_now()),
    }


def ok_object(data, status=200):
    return jsonify({
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def ok_array(items, limit, offset, total_count, has_more, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }), status


def paged(records, limit, offset, serializer, status=200):
    window, total, has_more = core.paginate(records, limit, offset)
    return ok_array([serializer(r) for r in window], limit, offset, total, has_more, status)


def error_body(error_id, message):
    return jsonify({
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })
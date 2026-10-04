"""Response envelope helpers (PRD §2.2, §2.3)."""

from flask import jsonify

from db import iso_now_wallclock, new_request_id


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now_wallclock(),
    }
    if extra:
        m.update(extra)
    return m


def _strip(entity):
    """Remove internal bookkeeping keys before serializing."""
    if isinstance(entity, dict):
        return {k: v for k, v in entity.items() if not k.startswith("_")}
    return entity


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _strip(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_response(items, limit, offset, total_count):
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [_strip(i) for i in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status

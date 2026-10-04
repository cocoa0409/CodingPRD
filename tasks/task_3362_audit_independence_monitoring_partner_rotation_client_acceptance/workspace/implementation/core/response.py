"""Standard response envelope helpers (scaffold §1.0)."""

from flask import jsonify

from .utils import format_timestamp, new_request_id, utcnow


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_timestamp(utcnow()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def envelope(data, response_type="object", pagination=None):
    return {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }


def send(data, status=200, response_type="object", pagination=None):
    return jsonify(envelope(data, response_type, pagination)), status


def send_list(rows, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(rows)) < total,
    }
    return send(rows, 200, "array", pagination)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }

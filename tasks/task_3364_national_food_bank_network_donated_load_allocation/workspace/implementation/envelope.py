"""The response envelope defined by PRD 2.2 / SCAFFOLD response_envelope."""

import random
import string

from flask import jsonify

import clock

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok_object(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def ok_empty(status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": {},
    }), status


def ok_array(items, limit, offset, total_count, status=200):
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), status


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }), status

"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": clock.real_now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def array_response(rows, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    """Offset pagination: limit/offset/total_count/has_more (PRD section 2.3)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }

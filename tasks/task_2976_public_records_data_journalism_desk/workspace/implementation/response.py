"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def object_response(payload, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": payload if payload is not None else {},
    }
    return jsonify(body), status


def created_response(payload):
    return object_response(payload, 201)


def array_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

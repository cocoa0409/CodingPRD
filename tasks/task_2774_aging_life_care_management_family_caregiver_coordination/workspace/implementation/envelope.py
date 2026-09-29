"""Response envelope helpers (PRD section 2.2 and 2.3)."""
import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }


def object_body(data):
    return {"meta": base_meta(), "response_type": "object", "data": data}


def ok(data, status=200):
    return jsonify(object_body(data)), status


def created(data):
    return ok(data, 201)


def page(items, limit, offset):
    """Apply pagination and render the array envelope."""
    total = len(items)
    window = items[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": window}), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }

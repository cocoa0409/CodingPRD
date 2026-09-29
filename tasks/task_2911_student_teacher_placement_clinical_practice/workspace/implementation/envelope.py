"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits

PAGE_DEFAULT = 1
PAGE_SIZE_DEFAULT = 10
PAGE_SIZE_MIN = 1
PAGE_SIZE_MAX = 100


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt_instant(clock.now()),
    }


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, page, page_size, total_count):
    meta = base_meta()
    meta["page"] = page
    meta["page_size"] = page_size
    meta["total_count"] = total_count
    meta["has_more"] = (page * page_size) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

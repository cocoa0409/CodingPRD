"""Response envelope helpers."""

import random
import string

from flask import jsonify

from db import iso, DB


def request_id():
    suffix = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(DB.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, response_type="object", pagination=None):
    meta = _meta(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), 200


def created(data):
    body, _ = success(data, "object")
    return body, 201


def array(data, pagination):
    return success(data, "array", pagination)


def no_data():
    return success({}, "object")


def error_body(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
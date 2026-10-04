"""Standard response envelope helpers."""

import random
import string

from flask import jsonify

from db import iso_now_wall
from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def success(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now_wall(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso_now_wall(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status

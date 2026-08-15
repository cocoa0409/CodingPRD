"""Standard response envelope helpers per PRD section 2.2."""

import random
import string
from flask import jsonify

from db import now_iso


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _meta(include_pagination: bool = False, limit=None, offset=None, total_count=None, has_more=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = has_more
    return m


def success_object(data, status_code: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit: int, offset: int, total_count: int, status_code: int = 200):
    has_more = (offset + limit) < total_count
    body = {
        "meta": _meta(True, limit, offset, total_count, has_more),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status

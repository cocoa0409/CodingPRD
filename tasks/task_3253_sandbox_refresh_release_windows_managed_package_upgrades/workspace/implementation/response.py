"""The standard response envelope (PRD §2.2).

Success:
    {"meta": {"api_request_id", "api_request_timestamp", ...pagination},
     "response_type": "object" | "array",
     "data": {...} | [...]}

Error:
    {"meta": {"api_request_id", "api_request_timestamp"},
     "response_type": "error",
     "data": {"error_id": ..., "message": ...}}

Pagination fields (limit, offset, total_count, has_more) are carried in the
``meta`` object and are included for list endpoints only (PRD §2.2, §2.3).
"""

import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.default_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(meta), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
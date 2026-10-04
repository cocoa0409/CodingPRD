"""Standard response envelope (PRD 2.2).

Success:
  { "meta": {"api_request_id", "api_request_timestamp", [pagination...]},
    "response_type": "object" | "array", "data": {...} }

Error:
  { "meta": {"api_request_id", "api_request_timestamp"},
    "response_type": "error",
    "data": {"error_id", "message"} }
"""

import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(16))


def meta(pagination=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": db.iso(db.now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None):
    return jsonify({
        "meta": meta(pagination),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def ok_list(items, limit, offset, total_count, status=200):
    return jsonify({
        "meta": meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), status


def error(error_id, message, status):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
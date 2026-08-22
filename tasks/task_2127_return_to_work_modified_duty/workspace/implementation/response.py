"""Standard response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": rows,
    }), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total

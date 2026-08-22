"""Standard response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import clock
import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.real_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    db.flush()
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, total_count, limit, offset):
    db.flush()
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

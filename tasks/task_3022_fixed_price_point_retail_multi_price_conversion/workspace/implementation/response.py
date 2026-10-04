"""Response envelope helpers (SCAFFOLD §1.5 response_envelope / PRD §2.2)."""

import random
import string

from flask import jsonify

from db import db, iso

ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(18))


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(db.logical_clock),
    }


def ok(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def ok_object(data, status=200):
    return ok(None if data is None else data, "object", status)


def ok_array(rows, total_count, limit, offset, status=200):
    has_more = (offset + len(rows)) < total_count
    meta_pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return ok(rows, "array", status, meta_pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
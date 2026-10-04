"""Standard response envelope helpers (scaffold §1.0, PRD §2.2)."""

import random
import string

from flask import jsonify

from clock import fmt_dt
import db

_ALPHABET = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def meta_extra():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": fmt_dt(db.now()),
    }


def ok(data, pagination=None, status=200):
    meta = meta_extra()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": "object", "data": data}), status


def array(items, pagination=None, status=200):
    meta = meta_extra()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error_body(error_id, message):
    return {
        "meta": meta_extra(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items, limit, offset):
    """Slice a list and build the four pagination meta fields."""
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination
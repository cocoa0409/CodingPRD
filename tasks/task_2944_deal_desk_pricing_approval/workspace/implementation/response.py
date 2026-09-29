"""Response envelope helpers (PRD 2.2)."""
import random
import string
from datetime import datetime, date
from decimal import Decimal

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt(clock.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def clean(value):
    """Recursively convert stored values into JSON-friendly primitives."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return clock.fmt(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": clean(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def no_content():
    return "", 204


def listing(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [clean(item) for item in items],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

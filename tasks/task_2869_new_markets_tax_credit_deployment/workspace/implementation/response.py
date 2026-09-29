"""Response envelope helpers (PRD section 2.2)."""
import random
import string
from decimal import Decimal

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now(),
    }


def public(value):
    """Project a stored row into its public JSON form."""
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": public(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

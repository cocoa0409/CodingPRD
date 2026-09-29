"""Response envelope helpers (PRD 2.2)."""
import random
import string
from decimal import Decimal

from flask import jsonify

import store

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_stamp(),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        f = float(value)
        return f
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(row):
    """Serialise a stored row, dropping internal (underscore-prefixed) keys."""
    if row is None:
        return {}
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_entity(row, status=200):
    return ok(public(row), status)


def ok_list(rows, limit, offset, total_count, serializer=public):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in rows],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

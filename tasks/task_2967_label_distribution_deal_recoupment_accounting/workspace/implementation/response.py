"""Response envelope helpers (PRD section 2.2, 2.3)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso_instant(db.store.now()),
    }


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(repr(value) + " is not JSON serialisable")


def _emit(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    envelope = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _emit(envelope, status)


def created(data):
    return ok(data, 201)


def empty():
    return ok({}, 200)


def collection(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    envelope = {"meta": meta, "response_type": "array", "data": items}
    return _emit(envelope, 200)


def error(error_id, message, status):
    envelope = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(envelope, status)

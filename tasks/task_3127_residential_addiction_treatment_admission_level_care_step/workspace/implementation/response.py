"""Response envelope helpers matching SCAFFOLD.yaml response_envelope."""

import json

from flask import Response

from common import iso
from db import STORE, new_request_id


def envelope(data, response_type="object", pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(STORE.now()),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return {"meta": meta, "response_type": response_type, "data": data}


def object_response(data, status=200):
    return _send(envelope(data, "object"), status)


def array_response(rows, pagination, status=200):
    return _send(envelope(rows, "array", pagination), status)


def error_response(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso(STORE.now()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _send(body, status)


def _send(body, status):
    payload = json.dumps(body, ensure_ascii=False, default=_fallback)
    return Response(payload, status=status, mimetype="application/json")


def _fallback(value):
    raise TypeError("not JSON serializable: %r" % (value,))
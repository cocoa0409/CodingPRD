"""Standard success/error response envelopes."""
import json
from decimal import Decimal

from flask import Response

from store import now_iso, request_id


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serializable")


def _dump(payload):
    return json.dumps(payload, default=_default)


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def respond(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return Response(_dump(body), status=status, mimetype="application/json")


def ok(data, status=200):
    return respond(data, status=status, response_type="object")


def created(data):
    return respond(data, status=201, response_type="object")


def listing(rows, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    }
    return respond(rows, status=200, response_type="array", meta_extra=meta_extra)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(_dump(body), status=status, mimetype="application/json")

"""The response envelope of PRD 2.2 and the pagination shape of PRD 2.3."""

import json
from decimal import Decimal

from flask import Response

from store import fmt_ts, request_id, wall_now


def _default(value):
    if isinstance(value, Decimal):
        as_float = float(value)
        if as_float == int(as_float):
            return as_float
        return as_float
    raise TypeError(repr(value) + " is not JSON serializable")


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(wall_now()),
    }


def _send(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    return _send({"meta": _meta(), "response_type": "object", "data": data}, status)


def created_response(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def list_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _send({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _send(payload, status)

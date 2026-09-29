"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        dt = obj.astimezone(timezone.utc)
        return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
            dt.microsecond // 1000)
    raise TypeError("not serializable: %r" % (obj,))


def _respond(body, status):
    return Response(json.dumps(body, default=_default), status=status,
                    mimetype="application/json")


def _meta():
    return {"api_request_id": request_id(),
            "api_request_timestamp": request_timestamp()}


def object_response(data, status=200):
    return _respond({"meta": _meta(), "response_type": "object",
                     "data": data}, status)


def created_response(data):
    return object_response(data, 201)


def list_response(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return _respond({"meta": meta, "response_type": "array", "data": page}, 200)


def error_response(error_id, message, status):
    return _respond({"meta": _meta(), "response_type": "error",
                     "data": {"error_id": error_id, "message": message}},
                    status)

"""Response envelope helpers per PRD section 2.2.

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""

import json
import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import Response

from db import iso, now


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": iso(now())}
    if extra:
        m.update(extra)
    return m


def _json_default(o):
    if isinstance(o, datetime):
        return iso(o)
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError("not JSON serializable: %r" % type(o))


def _respond(payload, status):
    return Response(
        json.dumps(payload, default=_json_default),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    return _respond({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return ok(data, 201)


def ok_list(items, total_count, limit, offset):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return _respond({"meta": _meta(meta), "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    return _respond(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )

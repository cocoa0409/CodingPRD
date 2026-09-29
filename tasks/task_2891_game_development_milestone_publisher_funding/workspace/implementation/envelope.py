"""The response envelope of PRD 2.2 and the pagination rules of PRD 2.3."""

import json
import random
import string
from decimal import Decimal
from fractions import Fraction

from flask import Response

from store import now_iso

_ALPHANUM = string.ascii_uppercase + string.digits

# PRD 2.3: limit "defaults to 10 when omitted, accepts a minimum of 1 and a
# maximum of 100"; offset "is the number of records to skip and defaults to 0".
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


def _default(value):
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(repr(value))


def _respond(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def success(data, status=200):
    return _respond(
        {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}},
        status,
    )


def created(data):
    return success(data, 201)


def collection(items, limit, offset):
    """List envelope: data is an array and meta repeats the pagination fields."""
    total = len(items)
    window = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    return _respond({"meta": meta, "response_type": "array", "data": window}, 200)


def failure(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)

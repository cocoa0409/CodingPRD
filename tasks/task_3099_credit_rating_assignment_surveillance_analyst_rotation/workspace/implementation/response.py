"""Response envelope helpers.

Envelope shape is taken verbatim from PRD section 2.2 / SCAFFOLD
response_envelope: meta (api_request_id, api_request_timestamp), response_type
("object" / "array" / "error") and data.  List responses add the pagination
fields limit / offset / total_count / has_more inside meta.
"""

import json
import random
import string
from datetime import timezone
from decimal import Decimal

from flask import Response

from db import iso, now

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _jsonify(payload, status):
    body = json.dumps(payload, default=_default, separators=(",", ":"))
    return Response(body, status=status, mimetype="application/json")


def _default(value):
    if isinstance(value, Decimal):
        as_float = float(value)
        if as_float == int(as_float):
            return int(as_float)
        return as_float
    if hasattr(value, "isoformat"):
        return iso(value)
    raise TypeError("cannot serialise %r" % (value,))


def ok(data, status=200):
    """Single-resource success envelope."""
    return _jsonify({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    """Array envelope with the pagination fields in meta."""
    return _jsonify(
        {
            "meta": _meta(
                {
                    "limit": limit,
                    "offset": offset,
                    "total_count": total_count,
                    "has_more": offset + len(items) < total_count,
                }
            ),
            "response_type": "array",
            "data": items,
        },
        200,
    )


def error_body(error_id, message, status):
    """Error envelope — meta carries only the two request fields."""
    return _jsonify(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
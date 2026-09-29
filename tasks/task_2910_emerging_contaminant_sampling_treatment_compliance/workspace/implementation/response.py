"""Response envelope (PRD section 2.2) plus an exact-precision JSON writer.

Numbers that carry a declared decimal precision are stored as ``Decimal`` values
quantized to that precision, and are emitted with exactly that many fractional
digits (``0.00``, ``2.15``, ``0.5375``).  Python's ``json`` module cannot do that
for ``Decimal``, so this module writes JSON itself.
"""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def _format_decimal(value):
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int) or exponent > 0:
        value = value.quantize(Decimal(1))
    text = format(value, "f")
    return text


def _write(value, out):
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, Decimal):
        out.append(_format_decimal(value))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(repr(value))
    elif isinstance(value, str):
        out.append(json.dumps(value))
    elif isinstance(value, datetime):
        out.append(json.dumps(format_instant(value)))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        first = True
        for item in value:
            if not first:
                out.append(",")
            first = False
            _write(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        first = True
        for key, item in value.items():
            if not first:
                out.append(",")
            first = False
            out.append(json.dumps(str(key)))
            out.append(":")
            _write(item, out)
        out.append("}")
    else:
        out.append(json.dumps(str(value)))


def dumps(value):
    out = []
    _write(value, out)
    return "".join(out)


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": format_instant(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def _respond(body, status):
    return Response(dumps(body), status=status, mimetype="application/json")


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return _respond(body, status)


def created_response(data):
    return object_response(data, 201)


def array_response(rows, limit, offset, total_count):
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    }
    body = {"meta": _meta(extra), "response_type": "array", "data": rows}
    return _respond(body, 200)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(body, status)

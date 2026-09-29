"""Response envelope helpers.

Success:  {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:    {"meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...}}
List responses add limit / offset / total_count / has_more inside meta.
"""
import json
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import Response

from util import iso

ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(16))


def _fmt_decimal(value):
    text = format(value, "f")
    return text


def _write(obj, out):
    if obj is None:
        out.append("null")
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif isinstance(obj, Decimal):
        out.append(_fmt_decimal(obj))
    elif isinstance(obj, int):
        out.append(str(obj))
    elif isinstance(obj, float):
        out.append(repr(obj))
    elif isinstance(obj, str):
        out.append(json.dumps(obj))
    elif isinstance(obj, datetime):
        out.append(json.dumps(iso(obj)))
    elif isinstance(obj, dict):
        out.append("{")
        first = True
        for key, value in obj.items():
            if not first:
                out.append(", ")
            first = False
            out.append(json.dumps(str(key)))
            out.append(": ")
            _write(value, out)
        out.append("}")
    elif isinstance(obj, (list, tuple)):
        out.append("[")
        first = True
        for value in obj:
            if not first:
                out.append(", ")
            first = False
            _write(value, out)
        out.append("]")
    else:
        out.append(json.dumps(str(obj)))
    return out


def jdump(obj):
    return "".join(_write(obj, []))


def _meta(now):
    return {"api_request_id": request_id(), "api_request_timestamp": iso(now)}


def _respond(payload, status):
    return Response(jdump(payload), status=status, mimetype="application/json")


def ok(data, status=200, now=None):
    from store import db
    payload = {
        "meta": _meta(now or db.clock),
        "response_type": "object",
        "data": data,
    }
    return _respond(payload, status)


def ok_list(items, limit, offset, total_count, status=200, now=None):
    from store import db
    meta = _meta(now or db.clock)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return _respond(payload, status)


def error_response(error_id, message, status):
    from store import db
    payload = {
        "meta": _meta(db.clock),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)

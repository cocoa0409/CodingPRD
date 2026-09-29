"""Response envelope per PRD 2.2, with exact fixed-scale decimal rendering."""

import json
import random
import string
from decimal import Decimal

from flask import Response

from store import store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _fmt_decimal(d):
    s = format(d, "f")
    return s


def _encode(obj):
    """Serialise, rendering Decimal values as unquoted fixed-scale numbers."""
    subs = {}

    def conv(o):
        if isinstance(o, Decimal):
            key = "@@DEC%d@@" % len(subs)
            subs[key] = _fmt_decimal(o)
            return key
        if isinstance(o, dict):
            return {k: conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [conv(v) for v in o]
        return o

    text = json.dumps(conv(obj))
    for key, value in subs.items():
        text = text.replace('"%s"' % key, value)
    return text


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso,
    }
    if extra:
        meta.update(extra)
    return meta


def _respond(body, status):
    return Response(_encode(body), status=status, mimetype="application/json")


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return _respond(body, status)


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count, has_more):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return _respond(body, 200)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(body, status)

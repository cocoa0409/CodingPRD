"""Response envelope (PRD 2.2) and numeric-faithful JSON rendering."""

import json
import random
import re
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits
_DEC_RE = re.compile(r'"__DEC__(-?\d+(?:\.\d+)?)__"')


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _mark(value):
    """Recursively replace Decimal values with round-trippable marker strings."""
    if isinstance(value, Decimal):
        return "__DEC__" + format(value, "f") + "__"
    if isinstance(value, dict):
        return {k: _mark(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mark(v) for v in value]
    return value


def dump(payload):
    text = json.dumps(_mark(payload))
    return _DEC_RE.sub(r"\1", text)


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(stamp):
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": stamp or _now_iso(),
    }


def object_response(data, status=200, request_timestamp=None):
    body = {
        "meta": _meta(request_timestamp),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return Response(dump(body), status=status, mimetype="application/json")


def list_response(rows, limit, offset, total_count, request_timestamp=None):
    meta = _meta(request_timestamp)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return Response(dump(body), status=200, mimetype="application/json")


def error_response(error_id, message, status, request_timestamp=None):
    body = {
        "meta": _meta(request_timestamp),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(dump(body), status=status, mimetype="application/json")

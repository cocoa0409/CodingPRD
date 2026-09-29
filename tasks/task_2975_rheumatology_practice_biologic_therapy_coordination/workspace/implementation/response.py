"""Standard response envelope (PRD 2.2) and pagination meta (PRD 2.3)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def api_request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def _default(obj):
    if isinstance(obj, Decimal):
        # Exact decimals only ever come from validated JSON literals or from
        # quantized results, so the float round-trip is faithful.
        return float(obj)
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)


def _emit(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def _base_meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": api_request_timestamp(),
    }


def ok(data, status=200):
    """A single-resource or computed-read success envelope."""
    return _emit(
        {"meta": _base_meta(), "response_type": "object", "data": data if data is not None else {}},
        status,
    )


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    """A list success envelope: the four pagination fields live in meta."""
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error(error_id, message, status):
    return _emit(
        {
            "meta": _base_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )

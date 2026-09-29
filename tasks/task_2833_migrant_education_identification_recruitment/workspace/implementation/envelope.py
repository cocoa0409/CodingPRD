"""Response envelope helpers (PRD section 2.2).

Success:
  { "meta": {api_request_id, api_request_timestamp, [limit, offset, total_count,
    has_more]}, "response_type": "object"|"array", "data": ... }
Error:
  { "meta": {api_request_id, api_request_timestamp}, "response_type": "error",
    "data": {"error_id": ..., "message": ...} }
"""

import json
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def wall_timestamp():
    """ISO 8601 UTC instant with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        now.microsecond // 1000,
    )


# --------------------------------------------------------------------------
# Hand-rolled JSON writer so Decimal values render with their exact scale
# (e.g. 75.00 rather than 75.0) while still being JSON numbers.
# --------------------------------------------------------------------------

def _write(value, out):
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, Decimal):
        out.append(format(value, "f"))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(repr(value))
    elif isinstance(value, str):
        out.append(json.dumps(value))
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
    elif isinstance(value, (list, tuple)):
        out.append("[")
        first = True
        for item in value:
            if not first:
                out.append(",")
            first = False
            _write(item, out)
        out.append("]")
    else:
        out.append(json.dumps(str(value)))


def dumps(value):
    out = []
    _write(value, out)
    return "".join(out)


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_timestamp(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def _respond(body, status):
    return Response(dumps(body), status=status, mimetype="application/json")


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return _respond(body, status)


def success_list(rows, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": rows}
    return _respond(body, status)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(body, status)


def iso_from_epoch_ms(ms):
    dt = _EPOCH + timedelta(milliseconds=ms)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )

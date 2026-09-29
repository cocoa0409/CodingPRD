"""Response envelope of PRD 2.2 and the collection contract of PRD 2.3."""

import json
import random
import re
import string
from datetime import date, datetime
from decimal import Decimal

from flask import Response, request

from clock import clock
from errors import invalid_pagination

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day, value.hour, value.minute,
        value.second, value.microsecond // 1000)


def fmt_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return fmt_instant(obj)
    if isinstance(obj, date):
        return fmt_date(obj)
    raise TypeError("not JSON serialisable: %r" % (obj,))


def _base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(clock.now()),
    }


def _respond(body, status):
    return Response(json.dumps(body, default=_json_default),
                    status=status, mimetype="application/json")


def ok(data, status=200):
    return _respond({"meta": _base_meta(), "response_type": "object",
                     "data": data if data is not None else {}}, status)


def created(data):
    return ok(data, 201)


def error_response(error_id, message, status):
    return _respond({"meta": _base_meta(), "response_type": "error",
                     "data": {"error_id": error_id, "message": message}}, status)


_INT_RE = re.compile(r"^[+-]?\d+$")


def _int_param(name, default, minimum, maximum):
    if name not in request.args:
        return default
    raw = request.args.get(name, "")
    raw = raw.strip()
    if not _INT_RE.match(raw):
        raise invalid_pagination("%s must be an integer" % name)
    value = int(raw)
    if value < minimum:
        raise invalid_pagination("%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid_pagination("%s must be <= %d" % (name, maximum))
    return value


def read_pagination():
    """PRD 2.3 - limit defaults to 10 in [1, 100]; offset defaults to 0, >= 0."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def listing(rows, serializer):
    """Paginate an already-ordered, already-filtered row sequence."""
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array",
            "data": [serializer(r) for r in page]}
    return _respond(body, 200)

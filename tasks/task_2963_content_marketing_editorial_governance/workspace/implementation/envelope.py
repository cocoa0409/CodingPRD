"""Response envelope (PRD section 2.2) and pagination (PRD section 2.3)."""

import json
import random
import re
import string
from decimal import Decimal

from flask import Response, request

import timeutil
from errors import ApiError

_ID_ALPHABET = string.ascii_uppercase + string.digits
_DEC_TOKEN = "@@DEC@@"
_DEC_RE = re.compile(r'"' + _DEC_TOKEN + r'(-?\d+(?:\.\d+)?)@@"')

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return _DEC_TOKEN + format(o, "f") + "@@"
        return json.JSONEncoder.default(self, o)


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": timeutil.fmt(timeutil.now_wall()),
    }


def _render(payload, status):
    text = json.dumps(payload, cls=_Encoder)
    text = _DEC_RE.sub(r"\1", text)
    return Response(text, status=status, mimetype="application/json")


def ok(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return _render(payload, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, pagination):
    meta = _meta()
    meta.update(pagination)
    payload = {"meta": meta, "response_type": "array", "data": rows}
    return _render(payload, 200)


def error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _render(payload, status)


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not re.match(r"^[+-]?\d+$", text):
        raise ApiError("ERR_INVALID_REQUEST", name + " must be an integer")
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST", name + " is out of range")
    return value


def page(rows):
    """Apply limit/offset and build the four pagination meta fields."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }

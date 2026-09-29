"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import Response, request

from db import now_iso
from errors import ApiError
from util import dumps

ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def _send(body, status):
    payload = dumps(body)
    return Response(payload, status=status, mimetype="application/json")


def ok(data, status=200):
    return _send({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return ok(data, 201)


def no_content():
    return _send({"meta": _meta(), "response_type": "object", "data": {}}, 204)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _send(body, err.http_status)


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def page_params():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginated(items, serializer):
    """Apply limit/offset to an already-ordered list and build the envelope."""
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    body = {
        "meta": _meta(meta),
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return _send(body, 200)

"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    instant = datetime.now(timezone.utc)
    return "%s.%03dZ" % (instant.strftime("%Y-%m-%dT%H:%M:%S"),
                         instant.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


def _int_param(name, raw, default, minimum, maximum):
    if raw is None:
        return default
    if isinstance(raw, str):
        text = raw.strip()
        if text == "":
            raise ApiError("ERR_INVALID_REQUEST",
                           "'%s' must be an integer." % name)
        negative = text.startswith("-")
        digits = text[1:] if negative or text.startswith("+") else text
        if not digits.isdigit():
            raise ApiError("ERR_INVALID_REQUEST",
                           "'%s' must be an integer." % name)
        value = int(text)
    else:
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'%s' must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", request.args.get("limit"),
                       PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", request.args.get("offset"),
                        PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def listing(rows, serializer):
    """Apply pagination to already-filtered, already-ordered rows."""
    limit, offset = pagination()
    total = len(rows)
    page = paginate(rows, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, total)


def filtered(rows, spec):
    """Apply the optional, combinable equality filters of PRD 2.10."""
    out = rows
    for field, param in spec:
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [r for r in out
               if r.get(field) is not None and str(r.get(field)) == raw]
    return out

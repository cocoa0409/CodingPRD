"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def single(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def empty(status=200):
    return single({}, status)


def collection(items, total_count, limit, offset, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_body(error_id, message, http_status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    return value


def pagination():
    limit = _int_arg("limit", PAGINATION_LIMIT_DEFAULT)
    offset = _int_arg("offset", PAGINATION_OFFSET_DEFAULT)
    if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST",
                       "limit must be between %d and %d"
                       % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX))
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater")
    return limit, offset


def _bool_arg(raw):
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def apply_filters(items, spec):
    """spec maps query-parameter name -> ('str'|'int'|'bool', field name)."""
    for param, (kind, field) in spec.items():
        if param not in request.args:
            continue
        raw = request.args.get(param)
        if kind == "bool":
            wanted = _bool_arg(raw)
            if wanted is None:
                return []
            items = [i for i in items if bool(i.get(field)) is wanted]
        elif kind == "int":
            text = raw.strip()
            if not (text[1:] if text.startswith("-") else text).isdigit():
                return []
            wanted = int(text)
            items = [i for i in items if i.get(field) == wanted]
        else:
            items = [i for i in items if i.get(field) == raw]
    return items


def listing(items, spec=None, serializer=None):
    """Default list ordering is created_at ascending (insertion order)."""
    limit, offset = pagination()
    if spec:
        items = apply_filters(items, spec)
    items = sorted(items, key=lambda o: (o.get("created_at") or "", o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    if serializer is None:
        from db import serialize as serializer_fn
        serializer = serializer_fn
    return collection([serializer(i) for i in page], total, limit, offset)

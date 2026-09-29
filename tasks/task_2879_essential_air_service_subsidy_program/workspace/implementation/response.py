"""Standard response envelope (PRD section 2.2) and pagination (PRD section 2.3)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

import errors
from db import dec_places

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _emit(body, status):
    text = json.dumps(_jsonable(body))
    return text, status, {"Content-Type": "application/json"}


def ok(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": rows}, 200)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return _emit(error_body(error_id, message), status)


def page_params():
    """Read and validate limit/offset from the query string."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset may not be negative.")
    return limit, offset


def _as_int(raw):
    text = raw.strip()
    if text == "":
        errors.fail(errors.ERR_INVALID_REQUEST, "Pagination parameters must be integers.")
    try:
        return int(text)
    except ValueError:
        errors.fail(errors.ERR_INVALID_REQUEST, "Pagination parameters must be integers.")


def paginate(rows, serializer):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)


__all__ = [
    "ok", "created", "listing", "error_body", "error_response",
    "page_params", "paginate", "dec_places",
]

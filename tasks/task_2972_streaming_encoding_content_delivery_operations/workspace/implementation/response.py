"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import json
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import Response, request

from db import iso, now
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }


def _default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    raise TypeError(repr(value) + " is not JSON serializable")


def _emit(body, status):
    text = json.dumps(body, default=_default)
    return Response(text, status=status, mimetype="application/json")


def _clean(value):
    """Drop private bookkeeping keys and normalise instants for the wire."""
    if isinstance(value, dict):
        return dict(
            (k, _clean(v)) for k, v in value.items() if not k.startswith("_")
        )
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, datetime):
        return iso(value)
    return value


def ok(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": _clean(data)}, status)


def created(data):
    return ok(data, 201)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _emit(body, err.http_status)


PAGE_DEFAULT = 1
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MIN = 1
PAGE_SIZE_MAX = 100


def read_page_params(args=None):
    """page is 1-based; out-of-range values are refused, never clamped."""
    if args is None:
        args = request.args
    page = PAGE_DEFAULT
    page_size = PAGE_SIZE_DEFAULT
    if "page" in args:
        raw = args.get("page")
        if raw is None or not str(raw).strip().lstrip("-").isdigit():
            raise ApiError("ERR_INVALID_REQUEST", "page must be an integer")
        page = int(str(raw).strip())
        if page < 1:
            raise ApiError("ERR_INVALID_REQUEST", "page must be at least 1")
    if "page_size" in args:
        raw = args.get("page_size")
        if raw is None or not str(raw).strip().lstrip("-").isdigit():
            raise ApiError("ERR_INVALID_REQUEST", "page_size must be an integer")
        page_size = int(str(raw).strip())
        if page_size < PAGE_SIZE_MIN or page_size > PAGE_SIZE_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "page_size must be between %d and %d" % (PAGE_SIZE_MIN, PAGE_SIZE_MAX),
            )
    return page, page_size


def paginated(items, serializer, page, page_size):
    total = len(items)
    start = (page - 1) * page_size
    window = items[start:start + page_size]
    meta = _meta()
    meta["page"] = page
    meta["page_size"] = page_size
    meta["total_count"] = total
    meta["has_more"] = (start + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [_clean(serializer(row)) for row in window],
    }
    return _emit(body, 200)

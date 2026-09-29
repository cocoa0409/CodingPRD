"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import json

from flask import Response, request

import db as store
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


class Result(object):
    """What a handler returns: an entity reference, a list, or a raw payload."""

    def __init__(self, payload, status=200, kind="object", meta=None):
        self.payload = payload
        self.status = status
        self.kind = kind
        self.meta = meta or {}


def obj(entity, status=200):
    return Result(entity, status=status, kind="object")


def created(entity):
    return Result(entity, status=201, kind="object")


def raw(payload, status=200):
    return Result(payload, status=status, kind="raw")


def base_meta():
    return {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.fmt_instant(store.wall_now()),
    }


def _dump(body, status):
    return Response(
        json.dumps(body, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def build(result):
    meta = base_meta()
    if result.kind == "raw":
        data = result.payload
        response_type = "object"
    elif result.kind == "array":
        data = [store.serialize(e) for e in result.payload]
        response_type = "array"
        meta.update(result.meta)
    else:
        data = store.serialize(result.payload) if result.payload is not None else {}
        response_type = "object"
    return _dump(
        {"meta": meta, "response_type": response_type, "data": data}, result.status
    )


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _dump(body, status)


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def _as_int(value):
    text = value.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if digits == "" or not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "pagination parameters must be integers")
    number = int(digits)
    return -number if negative else number


def read_pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in request.args:
        limit = _as_int(request.args.get("limit"))
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if "offset" in request.args:
        offset = _as_int(request.args.get("offset"))
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must not be negative")
    return limit, offset


def paginate(items):
    """items must already be sorted; returns a list Result."""
    limit, offset = read_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return Result(page, status=200, kind="array", meta=meta)


def listing(items):
    return paginate(store.by_created(items))


def filtered(items, mapping):
    """mapping: query-parameter name -> entity field name."""
    for param, field in mapping.items():
        value = request.args.get(param)
        if value is None:
            continue
        items = [i for i in items if i.get(field) is not None and str(i[field]) == value]
    return items

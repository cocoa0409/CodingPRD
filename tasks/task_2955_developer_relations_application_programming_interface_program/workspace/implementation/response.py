"""Response envelope helpers.

Every response carries `meta` (api_request_id + api_request_timestamp), a
`response_type` discriminator and a `data` payload.
"""
import uuid

from flask import jsonify, request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
    PAGE_OFFSET_MIN,
)
from db import format_instant, store
from errors import invalid


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": format_instant(store.now()),
    }


def object_response(payload, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": payload}
    return jsonify(body), status


def array_response(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_arg(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        invalid("%s must be an integer." % name)
    value = int(text)
    if value < minimum:
        invalid("%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("%s must be <= %d." % (name, maximum))
    return value


def pagination():
    """Validated limit/offset pair; part of the request-shape rung."""
    limit = _int_arg("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_arg("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN)
    return limit, offset


def paginate(records, limit, offset, serializer):
    total = len(records)
    page = records[offset : offset + limit]
    return array_response([serializer(r) for r in page], total, limit, offset)


def enum_filter(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        invalid("%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def string_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw

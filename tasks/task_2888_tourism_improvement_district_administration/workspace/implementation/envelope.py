"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

import config
import store
from errors import fail


def _meta():
    return {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.iso3(store.wall_now()),
    }


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {} if data is None else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s may not be larger than %d." % (name, maximum))
    return value


def page_params():
    limit = _int_param("limit", config.PAGE_LIMIT_DEFAULT, config.PAGE_LIMIT_MIN, config.PAGE_LIMIT_MAX)
    offset = _int_param("offset", config.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(records, serializer, sort_key=None):
    """Apply the default (or supplied) ordering, then the window."""
    limit, offset = page_params()
    ordered = sorted(records, key=sort_key) if sort_key else store.sorted_records(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return listing([serializer(r) for r in window], total, limit, offset)


def enum_filter(name, allowed):
    """Read an optional enum-typed query filter, validating its membership."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def int_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)

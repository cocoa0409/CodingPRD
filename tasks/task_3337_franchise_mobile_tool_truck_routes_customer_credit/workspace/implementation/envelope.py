"""The response envelope, pagination and request-body validation helpers."""

import random
import string

from flask import jsonify, request

import clock
from errors import fail

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(18))


def meta(extra=None):
    payload = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt(clock.now()),
    }
    if extra:
        payload.update(extra)
    return payload


def ok(data, status=200, pagination=None):
    body = {"meta": meta(pagination), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, status=200, pagination=None):
    body = {"meta": meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body)


def paginate(items):
    """Apply limit/offset from the query string and return (page, meta_fields)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        limit = _int_arg(raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _int_arg(raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def _int_arg(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


# --------------------------------------------------------------------------
# Body helpers
# --------------------------------------------------------------------------

def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def require(payload, *names):
    for name in names:
        if name not in payload or payload[name] is None:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)


def as_str(payload, name, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or not value:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    return value


def as_int(payload, name, required=True, default=None, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d." % (name, maximum))
    return value


def as_bool(payload, name, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def as_enum(payload, name, allowed, required=True, default=None):
    value = as_str(payload, name, required=required, default=default)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def as_list(payload, name, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % name)
    return value


def filter_query(rows, mapping):
    """Apply simple equality filters named by `mapping` (query name -> field)."""
    result = rows
    for query_name, field in mapping.items():
        raw = request.args.get(query_name)
        if raw is None:
            continue
        if field == "is_new_launch":
            wanted = raw.lower() in ("true", "1", "yes")
            result = [r for r in result if bool(r.get(field)) == wanted]
        else:
            result = [r for r in result if str(r.get(field)) == raw]
    return result

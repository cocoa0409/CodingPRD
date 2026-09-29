"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    v = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000)


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def ok(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message, http_status):
    body = {"meta": base_meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status


def pagination_args():
    """limit defaults to 10 (1..100); offset defaults to 0."""
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def apply_filters(records, mapping):
    """Filter a list of records by the query parameters named in mapping.

    mapping maps query-parameter name -> record field name. A parameter that the
    caller did not supply is ignored; a supplied value that matches nothing
    simply yields an empty page.
    """
    out = list(records)
    for param, field in mapping.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        out = [r for r in out if str(r.get(field)) == raw]
    return out

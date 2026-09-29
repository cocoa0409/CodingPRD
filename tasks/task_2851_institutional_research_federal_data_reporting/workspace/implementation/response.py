"""Response envelope helpers (PRD 2.2 / 2.3)."""
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail
from util import new_request_id

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    # api_request_timestamp is request metadata, not a business instant: real UTC now.
    now = datetime.now(timezone.utc)
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def page_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (PRD 2.3)."""
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def filter_eq(rows, spec):
    """Apply the conjunctive equality filters declared for a listing (PRD 2.3).

    `spec` maps a query-parameter name to the row key it filters on.
    """
    out = rows
    for param, key in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if raw == "null":
            out = [r for r in out if r.get(key) is None]
            continue
        if raw in ("true", "false"):
            wanted = (raw == "true")
            out = [r for r in out if r.get(key) is wanted or r.get(key) == wanted]
            continue
        matched = []
        for r in out:
            value = r.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                continue
            if str(value) == raw:
                matched.append(r)
        out = matched
    return out

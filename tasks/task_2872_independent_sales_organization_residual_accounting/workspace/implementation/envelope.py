"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""
from flask import jsonify, request

from apierrors import fail
from store import db, request_id

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": db.now_iso()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def _page_int(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None:
        return default
    text = raw.strip()
    if text == "" or not (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def pagination():
    limit = _page_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _page_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), 200


def apply_filters(rows, spec):
    """spec: iterable of (query-parameter-name, row-key) pairs. Exact string match."""
    for param, key in spec:
        value = request.args.get(param)
        if value is None:
            continue
        rows = [r for r in rows if r.get(key) is not None and str(r.get(key)) == value]
    return rows

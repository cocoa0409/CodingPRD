"""PRD 2.2 response envelope and PRD 2.3 pagination."""

from flask import jsonify

from errors import ApiError
from store import jsonable, iso, now, request_id, ordered

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": iso(now())}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [jsonable(i) for i in items]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


def _int_param(raw, name):
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    return -int(digits) if negative else int(digits)


def pagination(args):
    """limit defaults to 10 (1..100), offset defaults to 0 (>= 0); out of range is a 400."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        limit = _int_param(args.get("limit"), "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    if "offset" in args:
        offset = _int_param(args.get("offset"), "offset")
        if offset < PAGINATION_DEFAULT_OFFSET:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(records, args, serializer):
    """Filters are already applied; total_count counts matches before pagination."""
    limit, offset = pagination(args)
    rows = ordered(records)
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)


def enum_filter(args, name, domain):
    """Query filters are inputs too: an undeclared enum member is a 400."""
    if name not in args:
        return None
    value = args.get(name)
    if value not in domain:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(sorted(domain))))
    return value

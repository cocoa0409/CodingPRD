"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from store import db, request_id


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)
    return {"api_request_id": request_id(), "api_request_timestamp": ts}


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
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def _parse_int_param(raw, name):
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    try:
        return int(text)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)


def pagination():
    """Returns (limit, offset); raises ERR_VALIDATION when out of range."""
    args = request.args
    limit = DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        limit = _parse_int_param(args.get("limit"), "limit")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if "offset" in args:
        offset = _parse_int_param(args.get("offset"), "offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def list_response(rows, serializer):
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list([serializer(r) for r in page], limit, offset, total)


def filter_eq(rows, param, field):
    """Apply an optional conjunctive equality filter from the query string."""
    value = request.args.get(param)
    if value is None:
        return rows
    return [r for r in rows if str(r.get(field)) == value]

"""The response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

from flask import jsonify, request

from errors import ApiError
from store import fmt_instant, request_id, wall_now

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(wall_now()),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(api_error):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(payload), api_error.http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text or not _is_plain_int(text):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    parsed = int(text)
    if parsed < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, minimum))
    if maximum is not None and parsed > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must not exceed %d." % (name, maximum))
    return parsed


def _is_plain_int(text):
    body = text[1:] if text[0] in "+-" else text
    return len(body) > 0 and body.isdigit()


def pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0)."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def enum_filter(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Unrecognised %s filter value." % name)
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def int_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    if not text or not _is_plain_int(text):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    return int(text)


def paginate(records, limit, offset, serializer):
    total = len(records)
    window = records[offset:offset + limit]
    return ok_list([serializer(record) for record in window], limit, offset, total)

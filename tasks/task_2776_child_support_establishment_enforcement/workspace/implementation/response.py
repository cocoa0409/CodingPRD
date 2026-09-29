"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

import db
import util
from errors import ApiError

LIMIT_PARAM = "limit"
OFFSET_PARAM = "offset"
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.iso_ts(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty(status=200):
    return ok({}, status)


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = str(raw).strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_VALIDATION", "%s is out of range." % name)
    return value


def page_params():
    limit = _int_param(LIMIT_PARAM, LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param(OFFSET_PARAM, OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(rows, serializer):
    """Apply the declared ordering, slice, and serialise."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], total, limit, offset)

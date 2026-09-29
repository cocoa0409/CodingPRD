"""Standard response envelope and pagination (PRD §2.2, §2.3)."""

from flask import jsonify, request

from errors import ApiError, ERROR_STATUS
from util import fmt_instant, new_request_id, now_real

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_instant(now_real()),
    }


def single(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def no_content():
    return "", 204


def collection(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message):
    return jsonify(error_body(error_id, message)), ERROR_STATUS.get(error_id, 400)


def _parse_int_param(raw):
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits or not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    value = int(digits)
    return -value if negative else value


def read_pagination():
    """Effective (limit, offset), rejecting out-of-bound values (PRD §2.3)."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _parse_int_param(raw_limit)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX),
            )
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _parse_int_param(raw_offset)
        if offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def page(records, limit, offset):
    """Apply the page window to an already ordered list."""
    total = len(records)
    return records[offset : offset + limit], total


def enum_filter(name, allowed):
    """Read an optional enum-valued query filter, rejecting undeclared members."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s holds an undeclared value." % name)
    return raw


def str_filter(name):
    return request.args.get(name)


def listed(records, serializer):
    """Paginate an already ordered record list and render the array envelope."""
    limit, offset = read_pagination()
    items, total = page(records, limit, offset)
    return collection([serializer(r) for r in items], limit, offset, total)

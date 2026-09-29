"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

import errors
import store

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.fmt_iso(store.wall_now()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty(status=200):
    return ok({}, status)


def listing(rows, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "%s must be an integer" % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "%s is outside the permitted range" % name)
    return value


def pagination():
    """Returns (limit, offset); ERR_INVALID_REQUEST when out of bounds."""
    limit = _int_arg("limit", PAGINATION_DEFAULT_LIMIT,
                     PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_arg("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def collection(rows, serializer, limit, offset):
    """Order, paginate and serialize a filtered row set."""
    ordered = store.order_rows(rows)
    page, total = paginate(ordered, limit, offset)
    return listing([serializer(r) for r in page], total, limit, offset)

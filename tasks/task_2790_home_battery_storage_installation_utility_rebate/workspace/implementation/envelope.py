"""Response envelopes (PRD 2.2) and list pagination (PRD 2.3)."""

from flask import jsonify, request

from common import new_request_id, wall_now_iso
from errors import invalid
from store import views

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty():
    return ok({}, 200)


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
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise invalid("Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise invalid("Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def page_params():
    limit = _int_param("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def collection(records):
    """Paginate an already-filtered, already-ordered record list."""
    limit, offset = page_params()
    total = len(records)
    page = records[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        },
        "response_type": "array",
        "data": views(page),
    }
    return jsonify(body), 200

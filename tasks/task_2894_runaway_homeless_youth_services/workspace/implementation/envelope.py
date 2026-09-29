"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

import store
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

# PRD 2.3 pagination defaults / bounds.
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    """PRD 2.2: 'a server-generated unique identifier for the request that starts
    with req_'."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        # PRD 2.5: every instant the server reports comes from the logical clock.
        "api_request_timestamp": store.iso(store.now()),
    }


def ok(data, status=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), status


def created(data):
    """PRD 4: 'Endpoints that bring a brand-new resource into existence answer with
    HTTP 201 Created.'"""
    return ok(data, 201)


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    # PRD 2.3: 'a non-integer value for either parameter is a request-shape failure'
    if text == "" or not (text.lstrip("+-").isdigit()):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d" % (name, maximum))
    return value


def page_args():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def listing(rows, serializer):
    """Paginate an already-ordered, already-filtered row list (PRD 2.3)."""
    limit, offset = page_args()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    # PRD 2.3: true exactly when records matching the filter remain beyond the window.
    meta["has_more"] = offset + len(window) < total
    return (
        jsonify({"meta": meta, "response_type": "array", "data": [serializer(r) for r in window]}),
        200,
    )


def enum_filter(name, allowed):
    """A query filter whose value must be a legal enum member (ladder rule 6)."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return raw

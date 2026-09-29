"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify

from db import iso, now, serialize

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    """PRD 2.2: a server-generated unique identifier that starts with `req_`."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }


def object_response(row, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(row) if row is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    """PRD 2.3: `meta` carries `limit` and `offset` as applied, `total_count`
    as the number of records matching the filter before pagination, and
    `has_more` as true when records remain beyond the current page."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status

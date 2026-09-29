"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

from store import now_iso, public

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    """rows: the full filtered set in canonical order (list of records)."""
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in window],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }

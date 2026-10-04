"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0)."""

import random
import string

from flask import jsonify

from store import iso, now

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    body = "".join(random.choice(_ALPHABET) for _ in range(18))
    return "req_" + body


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, status=200):
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })
    payload = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(payload), status


def error_body(error_id, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return payload


def base_list(items, limit, offset, status=200):
    """Alias used by the route modules for paginated list responses."""
    return listing(items, limit, offset, status)


def drift_response(error_id="ERR_DERIVED_FIELD_DRIFT", status=409):
    from errors import DEFAULT_MESSAGES
    message = DEFAULT_MESSAGES.get(
        error_id, "A computed field no longer matched its calculation and was repaired."
    )
    return jsonify(error_body(error_id, message)), status
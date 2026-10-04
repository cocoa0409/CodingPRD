"""Response envelope and serialisation helpers — PRD §2.2 / §2.3.

Success:
    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "...",
                "limit": 10, "offset": 0, "total_count": 100, "has_more": true },
      "response_type": "object" | "array",
      "data": { } }

Error:
    { "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." } }
"""

from decimal import Decimal
from flask import jsonify

from core import new_request_id, now_iso, num, D


def serialize(value):
    """Deep-convert a stored row into a JSON-safe structure.

    Underscore-prefixed keys are server-side bookkeeping (epoch keys, carrier
    back-pointers) and are never part of a resource representation.
    """
    if isinstance(value, Decimal):
        return num(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()
                if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def envelope(data, response_type, status=200, page=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if page is not None:
        meta["limit"] = page["limit"]
        meta["offset"] = page["offset"]
        meta["total_count"] = page["total_count"]
        meta["has_more"] = page["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": serialize(data) if data is not None else {},
    }
    return jsonify(body), status


def ok(row, status=200):
    """A single-resource success response."""
    return envelope(row, "object", status)


def ok_empty(status=200):
    """§2.2: 'For 2xx responses with no data, it contains an empty object.'"""
    return envelope({}, "object", status)


def page_of(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return envelope(window, "array", 200, page)


def error_envelope(error):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error.error_id,
            "message": error.message,
        },
    }
    return jsonify(body), error.http_status
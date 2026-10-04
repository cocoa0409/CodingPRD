"""Response envelope helpers (PRD section 2.2 / SCAFFOLD response_envelope)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import db, format_iso


def _request_id():
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + tail


def _timestamp():
    # Server-generated ISO 8601 UTC, three fractional digits.
    return format_iso(datetime.now(timezone.utc))


def meta(pagination=None):
    meta_obj = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if pagination is not None:
        meta_obj.update(pagination)
    return meta_obj


def ok(data, status=200, pagination=None):
    return jsonify({"meta": meta(pagination), "response_type": "object", "data": data}), status


def ok_list(data, status=200, pagination=None):
    """Success envelope for a collection response (response_type "array")."""
    return jsonify({"meta": meta(pagination), "response_type": "array", "data": data}), status


def error(error_id, message, status):
    return (
        jsonify(
            {
                "meta": meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def paginate(rows, limit=None, offset=None):
    """Apply limit/offset defaults and build the meta pagination block."""
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(rows)
    window = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return window, pagination
"""Response envelope helpers.

Envelope shape is taken verbatim from SCAFFOLD.yaml `response_envelope` and
PRD.md 2.2 / 2.3:

  success  {"meta": {"api_request_id", "api_request_timestamp"},
            "response_type": "object" | "array",
            "data": ...}
  error    {"meta": {...}, "response_type": "error",
            "data": {"error_id": ..., "message": ...}}

List responses add limit / offset / total_count / has_more to `meta`.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_REQUEST_ID_ALPHABET = string.ascii_lowercase + string.digits

# Pagination contract (SCAFFOLD.yaml response_envelope.pagination_defaults)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def iso_timestamp(dt=None):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def new_request_id():
    return "req_" + "".join(random.choice(_REQUEST_ID_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def collection_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }), 200


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status

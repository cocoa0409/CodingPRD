"""Standard response envelope helpers.

Envelope shapes are transcribed from SCAFFOLD.yaml SS1.0 and PRD SS2.2:

  success: {"meta": {...}, "response_type": "object"|"array", "data": {...}}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id": ..., "message": ...}}

Pagination fields (limit, offset, total_count, has_more) are added to `meta`
for list endpoints.
"""

import random
import string

from flask import jsonify

from clock import now_iso

_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    """Server-generated request id starting with `req_`."""
    return "req_" + "".join(random.choices(_ALPHABET, k=16))


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array(items, limit, offset, total_count):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return jsonify({"meta": _meta(meta), "response_type": "array", "data": items}), 200


def error_body(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )
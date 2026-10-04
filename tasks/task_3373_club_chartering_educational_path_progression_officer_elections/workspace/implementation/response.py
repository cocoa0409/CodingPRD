"""Response envelope helpers.

The envelope is pinned by SCAFFOLD.yaml `response_envelope` and PRD section 2.2:
    { "meta": {...}, "response_type": "object" | "array" | "error", "data": ... }
Pagination fields (limit, offset, total_count, has_more) live in `meta` and are
only present on list reads.  Error responses carry only api_request_id and
api_request_timestamp in `meta`.
"""

import random
import string

from flask import jsonify

from db import iso, utcnow

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    suffix = "".join(random.choice(_ALPHABET) for _ in range(18))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(utcnow()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-resource / mutation success: response_type "object"."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array(items, limit=None, offset=None, total_count=None):
    """List success: response_type "array" with pagination fields in meta."""
    meta = _meta()
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset if offset is not None else 0
        meta["total_count"] = total_count if total_count is not None else len(items)
        meta["has_more"] = (meta["offset"] + len(items)) < meta["total_count"]
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(error_id, message, status):
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

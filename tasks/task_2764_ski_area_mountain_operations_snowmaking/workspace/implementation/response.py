"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

import db
from util import iso

_ALPHABET = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    db.commit()
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def deferred_object_response(data, status=200):
    """Envelope for payloads whose data was already materialised post-commit."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(rows, serializer, limit, offset):
    db.commit()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

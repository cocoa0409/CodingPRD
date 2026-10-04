"""Response envelope helpers per PRD §2.2 / §2.3 and SCAFFOLD §1.0."""

import secrets
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def new_uuid():
    return str(uuid.uuid4())


def iso_now():
    """Wall-clock timestamp for meta/created_at — always ISO 8601 UTC, 3 fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(),
    }


def success_object(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_array(items, total_count, limit, offset, http_status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status

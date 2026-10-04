"""Response envelope helpers — exact structure from SCAFFOLD response_envelope."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def ok(data, status=200):
    """Single-resource success envelope."""
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def listing_ok(items, limit, offset, total_count):
    """List success envelope with pagination fields in meta."""
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + limit) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status

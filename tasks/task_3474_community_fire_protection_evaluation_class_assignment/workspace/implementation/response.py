"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify


def _wall_iso():
    """api_request_timestamp: server-generated wall-clock UTC, 3 fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": _wall_iso(),
    }


def clean(value):
    """Recursively convert non-JSON-native values (Decimal -> int/float)."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def ok(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": clean(data),
    }
    return jsonify(body), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": clean(items)}
    return jsonify(body), 200


def error_payload(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }

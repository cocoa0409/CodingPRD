"""Response envelope helpers.

Envelope field names are read verbatim from SCAFFOLD.yaml §1.0:
  success: meta { api_request_id, api_request_timestamp }, response_type, data
  error:   meta { api_request_id, api_request_timestamp }, response_type: "error",
           data { error_id, message }
  pagination fields (in meta, for lists): limit, offset, total_count, has_more
"""

import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from flask import jsonify


def _json_safe(value):
    """Recursively convert Decimal -> float so jsonify can serialize the body."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _timestamp() -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(pagination: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success_object(data: dict, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _json_safe(data),
    }
    return jsonify(body), http_status


def success_list(items: list, limit: int, offset: int, total_count: int):
    has_more = (offset + limit) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": _json_safe(items),
    }
    return jsonify(body), 200


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status

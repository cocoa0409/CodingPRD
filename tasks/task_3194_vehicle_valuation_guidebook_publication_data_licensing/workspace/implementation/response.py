"""Response envelope helpers per PRD §2.2."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Optional

from flask import jsonify

from errors import ApiError


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (millisecond precision)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_now() -> str:
    return _now_iso()


def success(data: Any, status: int = 200, *,
            response_type: Optional[str] = None,
            limit: Optional[int] = None,
            offset: Optional[int] = None,
            total_count: Optional[int] = None,
            has_more: Optional[bool] = None):
    """Build the standard success envelope."""
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"

    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if response_type == "array":
        # Pagination fields are included for list endpoints (PRD §2.3)
        meta["limit"] = limit if limit is not None else 10
        meta["offset"] = offset if offset is not None else 0
        meta["total_count"] = total_count if total_count is not None else (len(data) if isinstance(data, list) else 0)
        if has_more is None:
            used_offset = meta["offset"]
            used_limit = meta["limit"]
            meta["has_more"] = (used_offset + used_limit) < meta["total_count"]
        else:
            meta["has_more"] = has_more

    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else ({} if response_type == "object" else []),
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp

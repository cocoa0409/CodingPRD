"""Response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _wall_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params per PRD §2.3. Returns (limit, offset).

    Defaults: limit=10, offset=0. Range: 1 <= limit <= 100, offset >= 0.
    Out-of-range or non-integer values are malformed input (ERR_INVALID_REQUEST).
    """
    from errors import invalid_request

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if isinstance(raw_limit, str) and raw_limit.strip() != str(limit) and not (
            raw_limit.strip().lstrip("+") == str(limit)
        ):
            # reject things like "10.5"
            if not raw_limit.strip().lstrip("+-").isdigit():
                raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit out of range")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if isinstance(raw_offset, str) and not raw_offset.strip().lstrip("+-").isdigit():
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset out of range")
    return limit, offset

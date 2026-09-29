"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError

ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def wall_now_iso():
    """ISO 8601 UTC with exactly three fractional digits (wall clock)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def paginated(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0). PRD 2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        limit = _positive_int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100 inclusive.")
    if raw_offset is not None:
        offset = _positive_int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must not be negative.")
    return limit, offset


def _positive_int(raw):
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_VALIDATION", "Pagination values must be integers.")
    value = int(digits)
    return -value if negative else value


def num(value):
    """Render an exact Decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value

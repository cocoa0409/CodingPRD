"""Response envelope helpers per SCAFFOLD §1.0 / PRD §2.2 and §2.3."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _request_timestamp():
    # Real wall-clock is fine for the meta request timestamp; the logical
    # clock governs business semantics, not the envelope metadata.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    assert isinstance(err, ApiError)
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset per PRD §2.3: default 10/0, min 1, max 100."""
    from errors import err_input, ERR_INVALID_REQUEST

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_input(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_input(ERR_INVALID_REQUEST, "limit must be between 1 and 100")

    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_input(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err_input(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items_sorted, limit, offset):
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, total

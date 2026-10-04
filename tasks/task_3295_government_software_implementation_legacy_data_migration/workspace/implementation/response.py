"""Response envelope helpers per PRD 2.2/2.3."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def meta_base():
    return {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()}


def success_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params. Invalid values -> ERR_INVALID_REQUEST."""
    from errors import raise_error, ERR_INVALID_REQUEST

    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit out of range")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit], len(items)

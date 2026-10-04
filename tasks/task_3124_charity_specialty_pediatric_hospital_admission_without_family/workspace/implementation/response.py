"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2, §2.3)."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import bad_request

_ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def request_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": request_timestamp(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
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
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params per PRD §2.3 (default 10, min 1, max 100, offset default 0)."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise bad_request("limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise bad_request("offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending (insertion-ordered dicts preserve creation order),
    apply offset/limit, and return (page, total_count, limit, offset)."""
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset

"""Response envelope helpers and shared utilities."""

import secrets
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify

from db import store


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    body = {
        "meta": meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), 201


def ok_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": m,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_body(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination():
    from flask import request
    from errors import err_invalid

    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    items_sorted = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def new_entity():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def clock_date():
    return store.clock_date()

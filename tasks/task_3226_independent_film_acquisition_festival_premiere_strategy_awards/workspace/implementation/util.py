# Shared helpers: ids, timestamps, response envelope, pagination.

import secrets
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify

import db
from errors import ApiError


def new_id():
    return str(uuid.uuid4())


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        datetime.now(timezone.utc).strftime("%f")[:3] + "Z"


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def success_obj(data, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_utc(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(data, total_count, limit, offset, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_utc(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(data)) < total_count,
        },
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_utc(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_limit_offset():
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: list sorted by (created_at, id). Returns (page, total, limit, offset)."""
    limit, offset = parse_limit_offset()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total, limit, offset


def touch(resource):
    resource["updated_at"] = now_utc()
    resource["version"] += 1


# --- datetime parsing / formatting -----------------------------------------

def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s must include a timezone offset" % field)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    frac = ("%06d" % dt.microsecond)[:3]
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + frac + "Z"


def clock_dt():
    return parse_dt(db.logical_clock)


from decimal import ROUND_HALF_UP, Decimal


def round_half_up_cents(value):
    """value is a Decimal; round half-up to integer cents, return int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

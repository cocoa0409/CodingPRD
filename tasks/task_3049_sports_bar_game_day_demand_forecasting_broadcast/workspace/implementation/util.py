"""Response envelope, auth, pagination, time helpers."""
import re
import uuid
from datetime import datetime, timezone, timedelta

from flask import request, jsonify

import db
from errors import unauthenticated, forbidden, invalid_request

ROLES = {"PlatformAdmin", "VenueManager", "Host", "Server", "Scheduler"}

LEAGUES = ["FF_NFL", "FF_NBA", "MLB", "NHL", "NCAA", "MMA", "BOXING", "ENTERTAINMENT"]
EVENT_KINDS = ["BASE", "OVERLAY", "PPV"]


def req_id():
    return "req_" + uuid.uuid4().hex[:20]


def iso_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    """Current timestamp string. Uses logical clock for created_at etc."""
    return iso_ts(db.now())


def success(data, code=200, response_type="object", pagination=None):
    meta = {"api_request_id": req_id(), "api_request_timestamp": iso_ts(db.now())}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_body(err):
    meta = {"api_request_id": req_id(), "api_request_timestamp": iso_ts(db.now())}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


def auth(allowed_roles):
    """Validate X-User-Role / X-User-ID headers then role permission."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise unauthenticated()
    if role not in allowed_roles:
        raise forbidden()
    return role


def parse_dt(s, field="timestamp"):
    if not isinstance(s, str):
        raise invalid_request(f"{field} must be an ISO 8601 string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise invalid_request(f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise invalid_request(f"Missing required field: {field}")
    return data[field]


def req_int(data, field, minimum=None):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"{field} must be >= {minimum}")
    return v


def req_str(data, field):
    v = require(data, field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} must be a string")
    return v


def paginate(items):
    """Apply limit/offset pagination; returns (page, pagination_meta)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": (offset + limit) < total}
    return page, meta


def list_response(items, code=200):
    page, meta = paginate(items)
    return success(page, code=code, response_type="array", pagination=meta)


def zip_miles(zip_a, zip_b):
    """Synthetic zip distance: absolute 3-digit prefix difference times 10."""
    a = re.sub(r"\D", "", str(zip_a))[:3] or "0"
    b = re.sub(r"\D", "", str(zip_b))[:3] or "0"
    return abs(int(a) - int(b)) * 10


def ceil_div(a, b):
    return -(-a // b)


def bump(rec):
    """Refresh updated_at and increment version on a mutable record."""
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def serialize(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso_ts(v)
        else:
            out[k] = v
    return out


def serialize_list(records):
    return [serialize(r) for r in records]

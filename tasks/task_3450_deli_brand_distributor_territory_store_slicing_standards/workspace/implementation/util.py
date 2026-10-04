"""Wire contract helpers: response envelope, pagination, auth, validation.

Implements PRD SS2.1 (headers/roles), SS2.2 (envelope), SS2.3 (pagination),
SS2.4 (identity/change tracking), and the shape checks of SS2.8 tier 4.
"""
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import store
from errors import ApiError, fail

ROLES = {"BrandAdmin", "DistributorRep", "RetailManager", "PlantScheduler", "SafetyOfficer"}

ALL_ROLES = ("BrandAdmin", "DistributorRep", "RetailManager", "PlantScheduler", "SafetyOfficer")

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", 400, field + " is required and must be an ISO 8601 timestamp string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("ERR_VALIDATION", 400, field + " is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        fail("ERR_VALIDATION", 400, field + " is required and must be a YYYY-MM-DD date string")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail("ERR_VALIDATION", 400, field + " is not a valid calendar date")
    return value


# ---------------------------------------------------------------------------
# response envelope (PRD SS2.2 / SS2.3)
# ---------------------------------------------------------------------------

def meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:16],
        "api_request_timestamp": fmt_ts(store.now()),
    }


def ok(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_array(items):
    m = meta()
    m.update({"limit": len(items), "offset": 0, "total_count": len(items), "has_more": False})
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def list_response(serialized_items):
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", 400, "offset must be an integer")
        offset = max(0, offset)
    total = len(serialized_items)
    page = serialized_items[offset:offset + limit]
    m = meta()
    m.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })
    return jsonify({"meta": m, "response_type": "array", "data": page}), 200


def error_response(exc):
    payload = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(payload), exc.http_status


# ---------------------------------------------------------------------------
# auth (PRD SS2.1, SS2.8 tiers 1-2)
# ---------------------------------------------------------------------------

def auth(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", 401, "missing or invalid X-User-ID / X-User-Role headers")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN", 403, "role " + role + " is not permitted on this endpoint")
    return role, uid


# ---------------------------------------------------------------------------
# request body shape validation (PRD SS2.8 tier 4)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        if request.data:
            fail("ERR_VALIDATION", 400, "request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", 400, "request body must be a JSON object")
    return data


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str):
        fail("ERR_VALIDATION", 400, field + " is required and must be a string")
    return v


def opt_str(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not isinstance(v, str):
        fail("ERR_VALIDATION", 400, field + " must be a string")
    return v


def req_int(b, field, min_value=None):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_VALIDATION", 400, field + " is required and must be an integer")
    if min_value is not None and v < min_value:
        fail("ERR_VALIDATION", 400, field + " must be >= %d" % min_value)
    return v


def opt_int(b, field, default=None, min_value=None):
    if field not in b or b[field] is None:
        return default
    return req_int(b, field, min_value)


def req_bool(b, field):
    v = b.get(field)
    if not isinstance(v, bool):
        fail("ERR_VALIDATION", 400, field + " is required and must be a boolean")
    return v


def opt_bool(b, field, default=False):
    if field not in b or b[field] is None:
        return default
    return req_bool(b, field)


def req_enum(b, field, allowed):
    v = b.get(field)
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_VALIDATION", 400, field + " must be one of " + ", ".join(sorted(allowed)))
    return v


def opt_enum(b, field, allowed, default):
    if field not in b or b[field] is None:
        return default
    return req_enum(b, field, allowed)


def req_array(b, field, non_empty=False):
    v = b.get(field)
    if not isinstance(v, list):
        fail("ERR_VALIDATION", 400, field + " is required and must be an array")
    if non_empty and not v:
        fail("ERR_VALIDATION", 400, field + " must not be empty")
    return v


def opt_array(b, field):
    if field not in b or b[field] is None:
        return None
    return req_array(b, field)


def req_dt(b, field):
    return parse_dt(b.get(field), field)


def opt_dt(b, field):
    if field not in b or b[field] is None:
        return None
    return parse_dt(b[field], field)


def req_date(b, field):
    return parse_date(b.get(field), field)


def sort_std(records):
    """Default list order: created_at ascending, insertion order breaks ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))

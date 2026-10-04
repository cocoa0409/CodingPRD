"""Response envelope, auth, body/field validation, pagination, time helpers."""
import re
import uuid
from datetime import datetime, date, timezone

from flask import request, jsonify

import state
from errors import ApiError

ROLES = {"StateAdmin", "CardholderServices", "Cardholder", "RetailerSystem"}


# ---------------------------------------------------------------- time helpers
def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return state.clock_now()


def now_iso():
    return iso3(state.clock_now())


def parse_iso_dt(value):
    """Parse an ISO 8601 datetime to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def iso_date(d):
    return d.isoformat() if d is not None else None


# ------------------------------------------------------------- response envelope
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(page, total, limit, offset):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": m, "response_type": "array", "data": page}), 200


def error_envelope(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# -------------------------------------------------------------------- auth
def authn():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return role, uid


def authed(allowed_roles):
    """Pipeline steps 1-2: authentication then role authorization."""
    role, uid = authn()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN")
    return role, uid


def cardholder_owns(role, uid, case_id):
    if role == "Cardholder" and uid != case_id:
        raise ApiError("ERR_FORBIDDEN")


def retailer_self(role, uid, retailer_id):
    if role == "RetailerSystem" and uid != retailer_id:
        raise ApiError("ERR_FORBIDDEN")


# ------------------------------------------------------------------ body fields
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return b


def req(b, field):
    if field not in b or b[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", f"missing required field: {field}")
    return b[field]


def req_str(b, field):
    v = req(b, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"field {field} must be a non-empty string")
    return v


def opt_str(b, field, default=None):
    v = b.get(field, default)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"field {field} must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, field):
    v = req(b, field)
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", f"field {field} must be an integer")
    return v


def opt_int(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    if not _is_int(b[field]):
        raise ApiError("ERR_INVALID_REQUEST", f"field {field} must be an integer")
    return b[field]


def opt_bool(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    if not isinstance(b[field], bool):
        raise ApiError("ERR_INVALID_REQUEST", f"field {field} must be a boolean")
    return b[field]


# ------------------------------------------------------------------ pagination
def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def list_response(items, serializer):
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)


def query_filter(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None

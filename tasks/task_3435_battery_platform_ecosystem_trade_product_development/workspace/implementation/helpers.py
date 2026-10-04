"""Response envelope, auth, pagination, and request-shape helpers.

Envelope field names are exactly those of SCAFFOLD response_envelope:
meta.api_request_id / meta.api_request_timestamp, response_type, data;
error body data.error_id / data.message; pagination fields limit, offset,
total_count, has_more inside meta for list responses.
"""
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import db
from constants import (
    PAGE_DEFAULT_LIMIT,
    PAGE_DEFAULT_OFFSET,
    PAGE_MAX_LIMIT,
    PAGE_MIN_LIMIT,
    ROLES,
)
from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- time ------
def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 instant; naive values are treated as UTC."""
    if not isinstance(value, str):
        fail("ERR_VALIDATION", f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        fail("ERR_VALIDATION", f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_service_date(value):
    """A claim service_date is a strict YYYY-MM-DD calendar date string."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("ERR_VALIDATION", "service_date must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_VALIDATION", "service_date is not a valid calendar date")


# ------------------------------------------------------------- envelope -----
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(db.clock_now()),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ----------------------------------------------------------------- auth -----
def authenticate():
    """Priority 1: X-User-Role present and declared; X-User-ID present."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES or not user_id:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid identity headers")
    return user_id, role


def authorize(allowed_roles):
    """Priority 1 + 2: authentication, then role membership for the endpoint."""
    user_id, role = authenticate()
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_FORBIDDEN", f"Role {role} is not authorized for this endpoint")
    return user_id, role


# ------------------------------------------------------------ pagination ----
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if str(limit) != raw_limit.strip() and not raw_limit.strip().isdigit():
            fail("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            fail("ERR_VALIDATION", "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer")
        if not raw_offset.strip().lstrip("-").isdigit():
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset out of range")
    return limit, offset


def page_window(items, limit, offset):
    """Sort by created_at ascending (stable: insertion order on ties), window."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    return ordered[offset:offset + limit], len(ordered)


# ------------------------------------------------------------- body shape ---
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def present(data, name):
    return name in data and data[name] is not None


def req_field(data, name):
    if not present(data, name):
        fail("ERR_VALIDATION", f"{name} is required")
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str):
        fail("ERR_VALIDATION", f"{name} must be a string")
    return v


def opt_str(data, name):
    if not present(data, name):
        return None
    v = data[name]
    if not isinstance(v, str):
        fail("ERR_VALIDATION", f"{name} must be a string")
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        fail("ERR_VALIDATION", f"{name} must be a boolean")
    return v


def check_int(v, name):
    if not isinstance(v, int) or isinstance(v, bool):
        fail("ERR_VALIDATION", f"{name} must be an integer")
    return v


def req_int(data, name, minimum=None, gt=None, multiple_of=None):
    v = check_int(req_field(data, name), name)
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", f"{name} is below its minimum")
    if gt is not None and v <= gt:
        fail("ERR_VALIDATION", f"{name} must be greater than {gt}")
    if multiple_of is not None and v % multiple_of != 0:
        fail("ERR_VALIDATION", f"{name} must be a multiple of {multiple_of}")
    return v


def check_num(v, name):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        fail("ERR_VALIDATION", f"{name} must be a number")
    return v


def req_num(data, name, gt=None, ge=None):
    v = check_num(req_field(data, name), name)
    if gt is not None and not v > gt:
        fail("ERR_VALIDATION", f"{name} must be greater than {gt}")
    if ge is not None and not v >= ge:
        fail("ERR_VALIDATION", f"{name} must be at least {ge}")
    return v


def check_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_VALIDATION", f"{name} must be one of {sorted(allowed)}")
    return v

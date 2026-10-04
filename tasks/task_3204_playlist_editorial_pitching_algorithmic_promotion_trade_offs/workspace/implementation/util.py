"""Shared utilities: errors, envelope, auth, datetime handling, validation."""
import json
import random
import re
import string
import uuid
from datetime import datetime, timezone

from flask import request, jsonify


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Identity / ids / timestamps
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _frac3(dt):
    return "%03d" % (dt.microsecond // 1000)


def wall_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + _frac3(now) + "Z"


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (common-field timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + _frac3(dt) + "Z"


def fmt_instant(dt):
    """System-stamped business instant (activated_on, scheduled_rotation_on)."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += "." + _frac3(dt)
    return base + "Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


ALPHA2 = re.compile(r"^[A-Z]{2}$")

# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def ok_object(data, status=200):
    body = {
        "meta": {"api_request_id": req_id(), "api_request_timestamp": wall_ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, total, limit, offset, status=200):
    body = {
        "meta": {
            "api_request_id": req_id(),
            "api_request_timestamp": wall_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(items) < total,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def err_response(e):
    body = {
        "meta": {"api_request_id": req_id(), "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = ["RightsHolder", "PlaylistEditor", "EditorialLead", "FraudAnalyst", "PlatformAdmin"]


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role %s is not permitted for this endpoint" % role)


# ---------------------------------------------------------------------------
# Request body / field validation helpers (all raise ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------

def body_json():
    raw = request.get_data()
    if not raw:
        return {}
    try:
        b = json.loads(raw)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "Request body is not valid JSON")
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def need(b, name):
    if name not in b or b[name] is None:
        err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return b[name]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_str(v, name, allow_empty=False):
    if not isinstance(v, str) or (not allow_empty and v == ""):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a non-empty string" % name)
    return v


def as_int(v, name):
    if not is_int(v):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    return v


def as_num(v, name):
    if not is_num(v):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a number" % name)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be one of %s" % (name, allowed))
    return v


def as_dt(v, name):
    dt = parse_dt(v)
    if dt is None:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime string" % name)
    return v, dt


def as_str_list(v, name):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an array of strings" % name)
    return v


# ---------------------------------------------------------------------------
# Pagination / list helpers
# ---------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except Exception:
            err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except Exception:
            err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def opt_enum_filter(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "Invalid value for filter %s" % name)
    return v


def opt_str_filter(name):
    return request.args.get(name)


def opt_bool_filter(name):
    v = request.args.get(name)
    if v is None:
        return None
    lv = v.lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    err("ERR_INVALID_REQUEST", 400, "Invalid value for filter %s" % name)


def pub(e):
    """Public view of an entity: strip internal '_' keys."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def list_response(items):
    """items: pre-filtered entities in insertion order (created_at ASC)."""
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([pub(i) for i in page], total, limit, offset)

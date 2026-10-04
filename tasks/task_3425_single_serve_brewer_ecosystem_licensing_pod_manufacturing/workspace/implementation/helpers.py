"""Shared helpers: error type, response envelope, auth, validation, pagination."""
import re
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify

from store import db, get_clock, next_seq

ROLES = (
    "PlatformAdmin", "LicensingManager", "QualityAuditor", "BrandManager",
    "OperationsDirector", "ProductionPlanner", "CategoryManager",
    "FinanceAnalyst", "SupportAgent",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err400(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def new_req_id():
    return "req_" + uuid.uuid4().hex


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(get_clock())


def meta_base():
    return {"api_request_id": new_req_id(), "api_request_timestamp": now_iso()}


def ok(data, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), code


def created(data):
    return ok(data, 201)


def list_ok(items, serializer):
    page, pag = paginate(items)
    meta = meta_base()
    meta.update(pag)
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": [serializer(x) for x in page],
    }), 200


def api_error_response(err):
    return jsonify({
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.status


def body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err400("Request body must be a JSON object")
    return data


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "Missing or unknown X-User-Role / X-User-ID headers")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN", 403,
                               "Role not permitted on this endpoint")
            request.user_id = uid
            request.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def need(b, field):
    val = b.get(field, None)
    if val is None:
        err400("Missing required field: %s" % field)
    return val


def v_str(b, field, required=True):
    val = b.get(field, None)
    if val is None:
        if required:
            err400("Missing required field: %s" % field)
        return None
    if not isinstance(val, str):
        err400("Field %s must be a string" % field)
    return val


def v_int(b, field, required=True, minv=None, maxv=None):
    val = b.get(field, None)
    if val is None:
        if required:
            err400("Missing required field: %s" % field)
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        err400("Field %s must be an integer" % field)
    if minv is not None and val < minv:
        err400("Field %s is below the allowed minimum" % field)
    if maxv is not None and val > maxv:
        err400("Field %s is above the allowed maximum" % field)
    return val


def v_bool(b, field, required=True):
    val = b.get(field, None)
    if val is None:
        if required:
            err400("Missing required field: %s" % field)
        return None
    if not isinstance(val, bool):
        err400("Field %s must be a boolean" % field)
    return val


def v_enum(b, field, allowed, required=True):
    val = v_str(b, field, required)
    if val is None:
        return None
    if val not in allowed:
        err400("Field %s must be one of: %s" % (field, ", ".join(allowed)))
    return val


def parse_dt_val(val):
    if not isinstance(val, str):
        err400("Datetime must be an ISO 8601 string")
    s = val
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        err400("Invalid ISO 8601 datetime: %s" % val)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_val(val):
    if not isinstance(val, str) or not _DATE_RE.match(val):
        err400("Date must be YYYY-MM-DD")
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        err400("Invalid calendar date: %s" % val)


def parse_period_val(val):
    if not isinstance(val, str):
        err400("Period must be a YYYY-MM string")
    m = _PERIOD_RE.match(val)
    if not m or not (1 <= int(m.group(2)) <= 12):
        err400("Period must be a well-formed YYYY-MM string")
    return val


def period_not_future(period):
    clock = get_clock()
    if (int(period[:4]), int(period[5:7])) > (clock.year, clock.month):
        err400("Period must not be after the current clock month")


def init_common(obj):
    ts = now_iso()
    obj["id"] = str(uuid.uuid4())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    obj["version"] = obj.get("version", 1) + 1
    obj["updated_at"] = now_iso()


def find(coll, rid):
    obj = db[coll].get(rid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % (rid,))
    return obj


def paginate(items):
    args = request.args
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            err400("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            err400("offset must be an integer")
    if limit < 1:
        err400("limit must be at least 1")
    if limit > 100:
        limit = 100
    if offset < 0:
        err400("offset must be at least 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }

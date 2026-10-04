import secrets
import string
from calendar import monthrange
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from functools import wraps
from flask import request, jsonify


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


ROLES = {"PlatformAdmin", "OpsManager", "Customer", "HaulerAgent"}


def guarded(roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise err("ERR_UNAUTHENTICATED", 401,
                          "Missing X-User-ID / X-User-Role headers or undeclared role value.")
            if role not in roles:
                raise err("ERR_FORBIDDEN", 403,
                          "Role is not permitted to perform this operation.")
            return fn(*a, **kw)
        return wrapper
    return deco


def _req_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return fmt_ts(datetime.now(timezone.utc))


def success(data, code=200, response_type="object", page_meta=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": wall_now_iso()}
    if page_meta:
        meta.update(page_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_response(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": wall_now_iso()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


# ---------- body / field validation ----------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return body[name]


def as_str(v, name):
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be a string." % name)
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer." % name)
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be a number." % name)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean." % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400,
                  "Field %s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return v


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except Exception:
        raise ValueError("bad datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_dt(v, name):
    try:
        return parse_dt(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime." % name)


def as_date(v, name):
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be a YYYY-MM-DD date." % name)
    try:
        d = datetime.strptime(v, "%Y-%m-%d")
    except Exception:
        raise err("ERR_INVALID_REQUEST", 400, "Field %s must be a YYYY-MM-DD date." % name)
    return d.replace(tzinfo=timezone.utc)


# ---------- pagination ----------

def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", 400, "limit and offset must be integers.")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", 400, "offset must be >= 0.")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": (offset + limit) < total}
    return page, meta


# ---------- decimal helpers ----------

def D(x):
    return Decimal(str(x))


def rhu(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dfloor(d):
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


def dceil(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ---------- month arithmetic ----------

def add_months(dt, months):
    m0 = dt.month - 1 + months
    y = dt.year + m0 // 12
    m = m0 % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def months_ceil(start, end):
    """Calendar months from start to end, any partial month rounded UP."""
    if end <= start:
        return 0
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, m) > end:
        m -= 1
    if add_months(start, m) < end:
        m += 1
    return m

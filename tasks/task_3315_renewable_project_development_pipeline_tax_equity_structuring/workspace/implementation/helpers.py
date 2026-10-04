"""Response envelope helpers, auth middleware, payload validation helpers."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

import db
from errors import raise_err

ROLES = {
    "DeveloperAdmin",
    "OriginationManager",
    "ProcurementLead",
    "ConstructionManager",
    "TaxCounsel",
    "InvestorManager",
    "LenderAgent",
    "Auditor",
    "PlatformAdmin",
}


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_from_epoch(ts):
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO8601 datetime string into epoch seconds (float)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def success_obj(data, status=200):
    return (
        {
            "meta": {"api_request_id": _req_id(), "api_request_timestamp": _now_iso()},
            "response_type": "object",
            "data": data,
        },
        status,
    )


def success_arr(data, limit, offset, total_count, status=200):
    has_more = (offset + len(data)) < total_count
    return (
        {
            "meta": {
                "api_request_id": _req_id(),
                "api_request_timestamp": _now_iso(),
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            },
            "response_type": "array",
            "data": data,
        },
        status,
    )


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def require_auth(allowed_roles):
    role = get_role()
    if role is None or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a declared role")
    if role not in allowed_roles:
        raise_err("ERR_FORBIDDEN", "Role not permitted for this endpoint")
    return role


def payload():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise_err("ERR_VALIDATION", f"Missing required field: {name}")
    return body[name]


def req_string(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", f"Field {name} must be a string")
    return v


def req_enum(body, name, choices):
    v = req_field(body, name)
    if v not in choices:
        raise_err("ERR_VALIDATION", f"Field {name} must be one of {sorted(choices)}")
    return v


def as_decimal(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise_err("ERR_VALIDATION", f"Field {name} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise_err("ERR_VALIDATION", f"Field {name} must be a number")
    if d.is_nan() or d.is_infinite():
        raise_err("ERR_VALIDATION", f"Field {name} must be a finite number")
    return d


def req_number(body, name):
    return as_decimal(req_field(body, name), name)


def opt_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return as_decimal(body[name], name)


def req_positive_number(body, name):
    d = req_number(body, name)
    if d <= 0:
        raise_err("ERR_VALIDATION", f"Field {name} must be positive")
    return d


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_VALIDATION", f"Field {name} must be an integer")
    return v


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        raise_err("ERR_VALIDATION", f"Field {name} must be a boolean")
    return body[name]


def req_iso(body, name):
    v = req_field(body, name)
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", f"Field {name} must be an ISO8601 datetime")


def money2(d):
    """Quantize a Decimal to 2dp round-half-up and return as float."""
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def dec2(v):
    """Convert a stored numeric to Decimal at full precision."""
    return Decimal(str(v))


def pagination_args():
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        raise_err("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def now_common(entity):
    """Stamp created_at/updated_at (iso strings) + version=1 on a new entity."""
    ts = iso_from_epoch(db.clock_now())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = iso_from_epoch(db.clock_now())
    entity["version"] += 1

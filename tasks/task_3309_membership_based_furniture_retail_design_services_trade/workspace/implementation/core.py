"""Shared core: in-memory store, logical clock, errors, envelope, auth helpers."""
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# ---------------------------------------------------------------------------
# In-memory store (empty at boot; no seeding)
# ---------------------------------------------------------------------------

db = {
    "members": {},
    "trade_accounts": {},
    "galleries": {},
    "products": {},
    "source_books": {},
    "orders": {},
    "order_lines": {},
    "production_slots": {},
    "consultations": {},
    "appointments": {},
    "returns": {},
}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_START}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_dt(s):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format aware datetime as ISO 8601 UTC with 3 fractional digits, Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_date(s):
    return date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def rhu(value):
    """Round half up to integer cents. value may be Decimal/float/int."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_frac(num, denom_mult):
    """round_half_up(num * denom_mult) using Decimal for exactness."""
    return int((Decimal(str(num)) * Decimal(str(denom_mult))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_GALLERY_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_CONSULTATION_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_TRADE_ACCOUNT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_TRADE_NOT_VERIFIED": 409,
    "ERR_ORDER_EMPTY": 422,
    "ERR_LINE_NON_CANCELABLE": 409,
    "ERR_SLOT_NOT_OPEN": 409,
    "ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID": 409,
    "ERR_PRODUCT_UNAVAILABLE": 422,
    "ERR_PRODUCT_KIND_MISMATCH": 422,
    "ERR_QUOTE_EXPIRED": 422,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 422,
    "ERR_RETURN_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_APPOINTMENT_EXISTS": 409,
    "ERR_CUSTOM_NON_RETURNABLE": 422,
    "ERR_DEPOSIT_REQUIRED": 422,
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 422,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message):
    return ApiError(error_id, ERROR_HTTP[error_id], message)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success_object(data, status=200):
    return {"meta": meta(), "response_type": "object", "data": data}, status


def success_empty(status=200):
    return {"meta": meta(), "response_type": "object", "data": {}}, status


def success_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return {"meta": m, "response_type": "array", "data": items}, 200


def error_body(e):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }, e.http_status


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_args():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = {
    "Anonymous", "Member", "TradeDesigner", "GalleryAssociate",
    "TradeReviewer", "ProductionPlanner", "HubOperator", "PlatformAdmin",
}


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or invalid X-User-Role / X-User-ID headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not allowed on this endpoint")


# ---------------------------------------------------------------------------
# Common resource helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def touch(res):
    res["updated_at"] = fmt_dt(clock_now())
    res["version"] += 1


def init_common(res):
    now = fmt_dt(clock_now())
    res["id"] = new_id()
    res["created_at"] = now
    res["updated_at"] = now
    res["version"] = 1
    return res


def member_pricing_tier(member):
    return "MEMBER" if member["status"] in ("ACTIVE", "GRACE") else "RETAIL"


# ---------------------------------------------------------------------------
# Request body helper
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_enum(value, allowed, field_name):
    if value not in allowed:
        raise err("ERR_INVALID_ENUM",
                  "Invalid value for %s: %r" % (field_name, value))
    return value


def check_int(value, field_name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field_name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST",
                  "%s must be >= %d" % (field_name, minimum))
    return value

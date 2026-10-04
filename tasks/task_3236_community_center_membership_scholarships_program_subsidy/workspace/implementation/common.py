"""Common helpers: envelope, auth, pagination, logical clock, decimal rounding."""
import os
import random
import string
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Logical clock (never wall-clock). Startup value: 2026-09-01T00:00:00Z
# ---------------------------------------------------------------------------

_CLOCK = {"dt": datetime(2026, 9, 1, 0, 0, 0)}


def now_dt():
    return _CLOCK["dt"]


def today():
    return _CLOCK["dt"].date()


def set_clock(dt):
    _CLOCK["dt"] = dt


def format_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_datetime(s):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_time_hhmm(s):
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.strptime(s, "%H:%M")
    except ValueError:
        return None
    return dt.time()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_BRANCH_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_CATEGORY_NOT_FOUND": 404,
    "ERR_SPACE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_BRANCH_CODE": 409,
    "ERR_DUPLICATE_DRAFT": 409,
    "ERR_DUPLICATE_ACTIVE_AWARD": 409,
    "ERR_CAMPAIGN_ALREADY_ACTIVE": 409,
    "ERR_CAMPAIGN_NOT_ACTIVE": 409,
    "ERR_HOUSEHOLD_CAP_EXCEEDED": 409,
    "ERR_DOCUMENTATION_MISSING": 400,
    "ERR_AWARD_INELIGIBLE": 409,
    "ERR_POOL_EXHAUSTED": 409,
    "ERR_POOL_WOULD_GO_NEGATIVE": 409,
    "ERR_HOLD_WINDOW_INVALID": 409,
    "ERR_HOLD_ALLOWANCE_EXCEEDED": 409,
    "ERR_REINSTATE_WINDOW_PASSED": 409,
    "ERR_REGISTRATION_WINDOW_CLOSED": 409,
    "ERR_MEMBER_PRIORITY_ONLY": 409,
    "ERR_MEMBER_ONLY_PROGRAM": 409,
    "ERR_SESSION_FULL": 409,
    "ERR_RATIO_CAPACITY_EXCEEDED": 409,
    "ERR_TIME_RANGE_INVALID": 400,
    "ERR_SPACE_CONFLICT": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PARTICIPANT_AGE_INVALID": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERR.get(error_id, 400)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _gen_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=16))
    return "req_" + suffix


def meta():
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": format_dt(now_dt()),
    }


def success_object(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    m = meta()
    m.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = {
    "AssociationAdmin",
    "BranchDirector",
    "ProgramCoordinator",
    "FrontDesk",
    "Member",
    "BoardMember",
}
ENTITY_BACKED_ROLES = {"Member"}


def auth():
    """Return (role, user_id). Raises ApiError(401)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header")
    if role in ENTITY_BACKED_ROLES and not user_id:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID header is required for entity-backed roles",
        )
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", f"Role {role} is not permitted for this endpoint")


def require_member_owner(role, user_id, owner_member_id):
    """Priority-2 member ownership check."""
    if role == "Member" and user_id != owner_member_id:
        raise ApiError("ERR_UNAUTHORIZED", "Member may only act on resources they own")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate(items):
    """items: full sorted list of serialized dicts. Returns flask response."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    window = items[offset:offset + limit]
    return success_list(window, limit, offset, total)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def round_cents(value):
    """Round a Decimal/numeric to integer cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def household_multiplier(n):
    m = Decimal("0.80") + Decimal("0.20") * Decimal(min(int(n), 12))
    return m.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}")

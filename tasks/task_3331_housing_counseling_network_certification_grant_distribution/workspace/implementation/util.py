import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from flask import jsonify, request


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("not a timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO-8601 with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = parse_dt(DEFAULT_CLOCK)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = LogicalClock()


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    # days in target month
    if month == 12:
        first_next = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        first_next = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = (first_next - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or malformed X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Invalid request payload"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Requested transition not defined from current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_posture_blocked(msg="Member compliance posture blocks this operation"):
    return ApiError("ERR_MEMBER_POSTURE_BLOCKED", 422, msg)


def err_not_chartered(msg="Operation requires charter_status CHARTERED"):
    return ApiError("ERR_MEMBER_NOT_CHARTERED", 422, msg)


def err_course_full(msg="Course is at capacity"):
    return ApiError("ERR_COURSE_FULL", 422, msg)


def err_prereq(msg="Course prerequisite not met"):
    return ApiError("ERR_PREREQUISITE_NOT_MET", 422, msg)


def err_window_closed(msg="Logical clock outside the permitted window"):
    return ApiError("ERR_WINDOW_CLOSED", 422, msg)


def err_cross_entity(msg="Cross-entity referential integrity violation"):
    return ApiError("ERR_CROSS_ENTITY_MISMATCH", 422, msg)


def err_pool_exhausted(msg="Allocation, disbursement or spending exceeds available amount"):
    return ApiError("ERR_POOL_EXHAUSTED", 422, msg)


def err_match_not_met(msg="verified_match_cents below required_match_cents"):
    return ApiError("ERR_MATCH_NOT_MET", 422, msg)


def err_duplicate(msg="Uniqueness constraint violated"):
    return ApiError("ERR_DUPLICATE", 409, msg)


def err_score_too_low(msg="Review score below competitive floor"):
    return ApiError("ERR_COMPETITIVE_SCORE_TOO_LOW", 422, msg)


def err_review_pending(msg="A file review is still OPEN or FAILED"):
    return ApiError("ERR_REVIEW_PENDING", 422, msg)


def err_hours_insufficient(msg="NO_OUTCOME requires at least 2.0 counseling hours"):
    return ApiError("ERR_OUTCOME_HOURS_INSUFFICIENT", 422, msg)


def err_cert_requirement(msg="Certification requirement unmet"):
    return ApiError("ERR_CERTIFICATION_REQUIREMENT_UNMET", 422, msg)


def err_not_reconcilable(msg="Award is not reconcilable"):
    return ApiError("ERR_AWARD_NOT_RECONCILABLE", 422, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(CLOCK.now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = {
    "NetworkDirector",
    "Assessor",
    "TrainingRegistrar",
    "GrantOfficer",
    "MemberAdmin",
    "ComplianceReviewer",
    "Auditor",
}


def auth():
    """Extract and validate identity headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err_unauthorized()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return data[name]


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    return value


def as_int_range(value, name, lo, hi):
    value = as_int(value, name)
    if value < lo or value > hi:
        raise err_invalid_request(f"Field {name} must be between {lo} and {hi}")
    return value


def as_nonneg_int(value, name):
    value = as_int(value, name)
    if value < 0:
        raise err_invalid_request(f"Field {name} must be >= 0")
    return value


def as_nonempty_str(value, name):
    if not isinstance(value, str) or not value.strip():
        raise err_invalid_request(f"Field {name} must be a non-empty string")
    return value


def as_enum(value, name, allowed):
    if value not in allowed:
        raise err_invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return value


def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full sorted list of serialized dicts."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------


def round_half_up_2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ceil_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_CEILING))


def floor_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))

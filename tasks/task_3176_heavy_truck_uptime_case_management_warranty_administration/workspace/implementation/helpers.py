"""Shared helpers: errors, envelope, timestamps, rounding, pagination, auth."""

import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from db import db


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Errors (exact catalog)
# ---------------------------------------------------------------------------

def err_missing_header():
    return ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
                    "X-User-ID or X-User-Role header missing or malformed", 400)


def err_forbidden():
    return ApiError("ERR_FORBIDDEN_FOR_ROLE",
                    "Role is not authorized for this endpoint", 403)


def err_actor_not_found():
    return ApiError("ERR_ACTOR_NOT_FOUND",
                    "entity_backed X-User-ID does not resolve", 404)


ERR_HTTP = {
    "ERR_FLEET_NOT_FOUND": 404,
    "ERR_TRUCK_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_DEALER_NOT_FOUND": 404,
    "ERR_BAY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_PART_ORDER_NOT_FOUND": 404,
    "ERR_PART_RETURN_NOT_FOUND": 404,
    "ERR_RECOVERY_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_FAULT_EVENT_NOT_FOUND": 404,
    "ERR_COVERAGE_CONTRACT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_COMPLETION_NOT_FOUND": 404,
    "ERR_FLEET_NOT_ACTIVE": 409,
    "ERR_TRUCK_DECOMMISSIONED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CASE_HAS_OPEN_CLAIM": 409,
    "ERR_BAY_TIME_CONFLICT": 409,
    "ERR_DEALER_NOT_AVAILABLE": 409,
    "ERR_CRITICAL_FAULT_WINDOW_LAPSED": 422,
    "ERR_RETURN_WINDOW_LAPSED": 422,
    "ERR_INVALID_COVERAGE_WINDOW": 422,
    "ERR_LABOR_MINUTES_EXCEED_STANDARD": 422,
    "ERR_RECOVERY_CLAIM_EXCEEDS_ALLOWANCE": 422,
    "ERR_RECOVERY_OVERPAID": 422,
    "ERR_INVALID_WORK_ORDER_WINDOW": 422,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_ODOMETER_REGRESSION": 422,
    "ERR_INVALID_CAMPAIGN_WINDOW": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CAMPAIGN_NOT_CLOSABLE": 409,
    "ERR_CASE_NOT_AWAITING_PART": 409,
    "ERR_CAMPAIGN_COMPLETION_MISMATCH": 409,
}


def api_err(error_id, message):
    return ApiError(error_id, message, ERR_HTTP[error_id])


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _wall_ts():
    """ISO 8601 UTC timestamp with three fractional digits (real clock)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Timestamps / rounding
# ---------------------------------------------------------------------------

def iso(dt):
    """Logical-clock timestamps rendered with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise api_err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise api_err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_cents(value):
    """Round a numeric/Decimal value to integer cents, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to 2 decimal places, half-up; returns float for JSON."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise api_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise api_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise api_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    rows_sorted = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(rows_sorted)
    page = rows_sorted[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = {"FleetManager", "UptimeCoordinator", "DealerAdvisor",
         "PartsManager", "WarrantyAdmin", "SupplierManager"}
ENTITY_BACKED = {"FleetManager": "fleets", "DealerAdvisor": "dealers"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Validate headers (p1), role authorization (p2), entity-backed actor (p3).

    Returns Actor. Raises ApiError otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err_missing_header()
    if not role or role not in ROLES:
        raise err_missing_header()
    if role not in allowed_roles:
        raise err_forbidden()
    if role in ENTITY_BACKED:
        coll = ENTITY_BACKED[role]
        if user_id not in getattr(db, coll):
            raise err_actor_not_found()
    return Actor(user_id, role)


def require_fields(body, fields):
    if not isinstance(body, dict):
        raise api_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    for f in fields:
        if f not in body or body[f] is None:
            raise api_err("ERR_INVALID_REQUEST", f"missing required field: {f}")
    return body


def opt_int(value, field, minimum=None):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise api_err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise api_err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return value


def req_int(body, field, minimum=None):
    if field not in body:
        raise api_err("ERR_INVALID_REQUEST", f"missing required field: {field}")
    return opt_int(body[field], field, minimum)


def opt_num(value, field):
    """Accept int/float (not bool), return Decimal."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise api_err("ERR_INVALID_REQUEST", f"{field} must be a number")
    return Decimal(str(value))


def opt_str(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise api_err("ERR_INVALID_REQUEST", f"{field} must be a string")
    return value


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise api_err("ERR_INVALID_REQUEST",
                      f"{field} must be one of {sorted(allowed)}")
    return v


def touch(entity):
    """Refresh updated_at and bump version on a common-fields entity."""
    entity["updated_at"] = iso(db.now())
    entity["version"] = entity.get("version", 1) + 1


def new_entity():
    import uuid
    now = iso(db.now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }

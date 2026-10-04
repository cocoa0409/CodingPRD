"""Shared utilities: logical clock, envelope, errors, auth, pagination."""
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone, date

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCED_NOT_FOUND = "ERR_REFERENCED_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CARRIER_NOT_ACTIVE = "ERR_CARRIER_NOT_ACTIVE"
ERR_RECIPROCITY_REQUIRED = "ERR_RECIPROCITY_REQUIRED"
ERR_PERMISSIBLE_PURPOSE = "ERR_PERMISSIBLE_PURPOSE"
ERR_CONSUMER_FILE_FROZEN = "ERR_CONSUMER_FILE_FROZEN"
ERR_DISPUTE_ALREADY_OPEN = "ERR_DISPUTE_ALREADY_OPEN"
ERR_DISPUTE_OVERDUE = "ERR_DISPUTE_OVERDUE"
ERR_BATCH_CONSTRAINT = "ERR_BATCH_CONSTRAINT"
ERR_INQUIRY_CAP_EXCEEDED = "ERR_INQUIRY_CAP_EXCEEDED"
ERR_EXCHANGE_RULE_EXISTS = "ERR_EXCHANGE_RULE_EXISTS"


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp (accepts trailing Z)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    return date.fromisoformat(value)


def fmt_dt(dt):
    """Logical-clock timestamps: no fraction when zero micros, else millis."""
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wallclock_now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": wallclock_now_iso(),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    args = request.args
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    """items: full sorted list of serialized dicts."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = {
    "PlatformAdmin",
    "ExchangeComplianceOfficer",
    "CarrierDataSteward",
    "CarrierUnderwriter",
    "Consumer",
}
ENTITY_BACKED_ROLES = {"CarrierDataSteward", "CarrierUnderwriter", "Consumer"}

PA = "PlatformAdmin"
ECO = "ExchangeComplianceOfficer"
CDS = "CarrierDataSteward"
CU = "CarrierUnderwriter"
CONS = "Consumer"

ALL_ROLES = [PA, ECO, CDS, CU, CONS]


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unknown X-User-Role / X-User-ID headers")
    if role in ENTITY_BACKED_ROLES and not uid:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-ID is required for entity-backed roles")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Role not permitted for this endpoint per RBAC matrix")


def require_owner(actor_id, owner_id):
    if actor_id != owner_id:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Acting identity does not own the target resource")


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


LOCK = threading.RLock()

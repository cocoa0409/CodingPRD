"""Request-scoped helpers: auth, body access, structural validators, pagination.

Structural (tier-9) validation raises ERR_VALIDATION. Handlers run higher-tier
checks first using the non-raising accessors (as_int / as_decimal / parse_dt),
then call the v_* validators at the structural tier.
"""
import calendar
import re
from datetime import datetime
from decimal import Decimal

from flask import request, jsonify

from store import ApiError, ok, parse_dt


ALL_ROLES = (
    "PlatformAdmin", "SupplyPlanner", "CustomerOps", "PlantOperator",
    "PipelineDispatcher", "TelemetryGateway", "QualityAnalyst",
    "QualityCertifier", "BillingSpecialist",
)

PRODUCTS = ("N2", "O2", "H2", "AR", "HE")


def respond(data, response_type="object", status=200, pagination=None):
    body, code = ok(data, response_type, status, pagination)
    return jsonify(body), code


# ---------------------------------------------------------------------------
# Tier 1 + 2: authentication and role authorization
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Role %s is not permitted for this endpoint" % role)


def forbidden(message):
    raise ApiError("ERR_UNAUTHORIZED_ROLE", 403, message)


# ---------------------------------------------------------------------------
# Body access and structural (tier-9) validation
# ---------------------------------------------------------------------------
def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def validation(message):
    raise ApiError("ERR_VALIDATION", 400, message)


def as_int(value):
    """Non-raising int coercion; None when not an integer value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def as_decimal(value):
    """Non-raising Decimal coercion for JSON numbers; None otherwise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def v_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            validation("Missing required field: %s" % field)
        return None
    if not isinstance(body[field], str):
        validation("Field must be a string: %s" % field)
    return body[field]


def v_int(body, field, required=True, min_value=None):
    if field not in body or body[field] is None:
        if required:
            validation("Missing required field: %s" % field)
        return None
    v = as_int(body[field])
    if v is None:
        validation("Field must be an integer: %s" % field)
    if min_value is not None and v < min_value:
        validation("Field %s must be >= %d" % (field, min_value))
    return v


def v_num(body, field, required=True, min_value=None):
    if field not in body or body[field] is None:
        if required:
            validation("Missing required field: %s" % field)
        return None
    d = as_decimal(body[field])
    if d is None:
        validation("Field must be a number: %s" % field)
    if min_value is not None and d < Decimal(str(min_value)):
        validation("Field %s must be >= %s" % (field, min_value))
    return body[field]


def v_bool(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            validation("Missing required field: %s" % field)
        return None
    if not isinstance(body[field], bool):
        validation("Field must be a boolean: %s" % field)
    return body[field]


def v_enum(body, field, values, required=True):
    v = v_str(body, field, required)
    if v is None:
        return None
    if v not in values:
        validation("Field %s must be one of %s" % (field, ", ".join(values)))
    return v


def v_dt(body, field, required=True):
    raw = v_str(body, field, required)
    if raw is None:
        return None
    if parse_dt(raw) is None:
        validation("Field must be an ISO 8601 datetime: %s" % field)
    return raw


def forbid(body, field):
    if field in body and body[field] is not None:
        validation("Field %s is forbidden for this variant" % field)


# ---------------------------------------------------------------------------
# Date / period helpers
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def v_date(body, field, required=True):
    raw = v_str(body, field, required)
    if raw is None:
        return None
    if parse_date(raw) is None:
        validation("Field must be an ISO date YYYY-MM-DD: %s" % field)
    return raw


def parse_period(value):
    """'YYYY-MM' -> (year, month) or None."""
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        return None
    year, month = int(value[:4]), int(value[5:7])
    if month < 1 or month > 12:
        return None
    return (year, month)


def v_period(body, field, required=True):
    raw = v_str(body, field, required)
    if raw is None:
        return None
    if parse_period(raw) is None:
        validation("Field must be a period YYYY-MM: %s" % field)
    return raw


def add_months(d, months):
    """Calendar-month addition with day clamping; d is a datetime.date."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = total // 12, total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    from datetime import date as _date
    return _date(year, month, day)


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------
def by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            validation("limit must be an integer")
        if limit < 1 or limit > 100:
            validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            validation("offset must be an integer")
        if offset < 0:
            validation("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta

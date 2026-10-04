"""Auth extraction (tier 1), role/ownership checks (tier 2) and body
field validators (tier 7 malformed-body checks)."""
from decimal import Decimal

from flask import request

import timeutil
from constants import ROLES
from errors import ApiError, ERR_INVALID_REQUEST, ERR_UNAUTHORIZED, unauthenticated, unauthorized


# --- Tier 1: authentication ---------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str):
        raise unauthenticated("X-User-ID header missing")
    if not role or role not in ROLES:
        raise unauthenticated("X-User-Role header missing or not a declared role")
    return uid, role


# --- Tier 2: authorization ----------------------------------------------------
def require_roles(role, allowed):
    if role not in allowed:
        raise unauthorized("role %s is not authorized for this endpoint" % role)


def check_gb_ownership(uid, role, owner_gb_id):
    """NGBAdmin is entity-backed: X-User-ID must equal the owning body id."""
    if role == "NGBAdmin" and owner_gb_id is not None and uid != owner_gb_id:
        raise unauthorized("NGBAdmin may only act on their own governing body")


def check_athlete_ownership(uid, role, owner_athlete_id):
    """Athlete is entity-backed: X-User-ID must equal the owning athlete id."""
    if role == "Athlete" and owner_athlete_id is not None and uid != owner_athlete_id:
        raise unauthorized("Athlete may only act on their own records")


# --- Body parsing -------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _bad(field, why):
    return ApiError(ERR_INVALID_REQUEST, 400, "field '%s' %s" % (field, why))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise _bad(field, "is required and must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or not v.strip():
        raise _bad(field, "must be a non-empty string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(field, "is required and must be an integer")
    return v


def opt_int(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(field, "must be an integer")
    return v


def req_num(body, field):
    """Numeric field -> Decimal (exact decimal parsing)."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _bad(field, "is required and must be a number")
    return Decimal(str(v))


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise _bad(field, "is required and must be a boolean")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise _bad(field, "must be a boolean")
    return v


def req_datetime(body, field):
    v = body.get(field)
    dt = timeutil.parse_dt(v)
    if dt is None:
        raise _bad(field, "is required and must be an ISO 8601 datetime")
    return dt


def req_date(body, field):
    v = timeutil.parse_date(body.get(field))
    if v is None:
        raise _bad(field, "is required and must be an ISO 8601 date (YYYY-MM-DD)")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise _bad(field, "is required and must be one of %s" % (sorted(allowed),))
    return v


def req_version(body, field):
    """OCC expected-version field: non-optional integer."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "field '%s' is required (optimistic concurrency)" % field)
    return v

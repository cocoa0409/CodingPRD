"""Auth middleware and shared request-validation helpers."""

from datetime import datetime

from flask import request

from db import db
from errors import (
    forbidden_for_role,
    invalid_request,
    missing_user_context,
    not_found,
)

ROLES = {"PortfolioManager", "PropertyAccountant", "OwnerRep", "RevenueAnalyst", "RiskOfficer"}

ALL_GET_ROLES = ROLES  # all five roles may call any GET endpoint


def current_user():
    """Validate X-User-ID and X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise missing_user_context()
    if not role or role not in ROLES:
        raise missing_user_context()
    return user_id.strip(), role


def require_roles(*roles):
    """Check auth headers then role permission. Returns (user_id, role)."""
    user_id, role = current_user()
    if role not in roles:
        raise forbidden_for_role()
    return user_id, role


def get_or_404(mapping, rid, msg="Resource not found"):
    if rid not in mapping:
        raise not_found(msg)
    return mapping[rid]


# ---- Body field helpers ----

def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise invalid_request(f"Missing or invalid required field: {field}")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Missing or invalid required field: {field}")
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise invalid_request(f"Field {field} must be an integer")
    return v


def req_num(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Missing or invalid required field: {field}")
    return v


def opt_num(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
        raise invalid_request(f"Field {field} must be a number")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None or v not in allowed:
        raise invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v is not None and v not in allowed:
        raise invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_iso(data, field):
    v = data.get(field)
    dt = parse_iso(v)
    if dt is None:
        raise invalid_request(f"Missing or invalid ISO8601 field: {field}")
    return dt


def parse_iso(v):
    if v is None or not isinstance(v, str):
        return None
    s = v
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def req_month(data, field):
    v = data.get(field)
    if not valid_month(v):
        raise invalid_request(f"Field {field} must be YYYY-MM")
    return v


def valid_month(v):
    if not isinstance(v, str) or len(v) != 7 or v[4] != "-":
        return False
    try:
        y = int(v[:4])
        m = int(v[5:7])
    except ValueError:
        return False
    return 1 <= m <= 12


def month_add(period_month, n):
    """Return period_month advanced by n months, in YYYY-MM."""
    y = int(period_month[:4])
    m = int(period_month[5:7])
    m += n
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def month_of(dt):
    return f"{dt.year:04d}-{dt.month:02d}"

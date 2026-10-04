"""Auth middleware (PRD §2.1) and request-body validation helpers."""
from flask import request

from errors import unauthenticated, forbidden, validation

ROLES = {"ResearchOps", "Analyst", "LicenseAdmin", "ComplianceOfficer", "FundCompanyRep"}


def require_auth():
    """Validate X-User-ID and X-User-Role headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Auth + RBAC (priority 1 then 2). Returns (user_id, role)."""
    user_id, role = require_auth()
    if role not in allowed:
        raise forbidden()
    return user_id, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise validation("Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise validation(f"Missing or invalid required field: {field}")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise validation(f"Field must be a string: {field}")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"Missing or invalid required field: {field}")
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise validation(f"Field must be an integer: {field}")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise validation(f"Missing or invalid required field: {field}")
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise validation(f"Invalid value for {field}: {v}")
    return v

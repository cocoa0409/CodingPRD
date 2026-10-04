# =============================================================================
# Auth middleware — X-User-ID / X-User-Role (PRD §2.1, validations 1-2)
# =============================================================================
from flask import request

from errors import missing_context, forbidden, validation

VALID_ROLES = {"PlatformAdmin", "IssuerOperator", "Cardholder", "CustomerService", "Any"}

# Roles that never bind X-User-ID to a persisted entity
OPAQUE_ROLES = {"PlatformAdmin", "IssuerOperator", "CustomerService", "Any"}


def get_caller():
    """Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    when headers are absent or the role value is not one of the five."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise missing_context()
    if not role or role not in VALID_ROLES:
        raise missing_context()
    return user_id, role


def require_roles(allowed):
    """Priority 1 + 2 (role membership). Returns (user_id, role)."""
    user_id, role = get_caller()
    if role not in allowed:
        raise forbidden("Role not permitted on this endpoint")
    return user_id, role


def require_cardholder_owner(row, fk_field="cardholder_id"):
    """Ownership check for entity-backed Cardholder callers (priority 2)."""
    user_id, role = require_roles(["Cardholder"])
    if row.get(fk_field) != user_id:
        raise forbidden("Cardholder does not own the target resource")
    return user_id, role


def get_body():
    """Parse the JSON body; None/empty becomes {}. Invalid JSON -> ERR_VALIDATION."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise validation("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


# ---- payload schema helpers (priority 3) ------------------------------------

def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise validation(f"{field} is required and must be a string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise validation(f"{field} must be a string")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise validation(f"{field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, minimum=0):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"{field} is required and must be an integer")
    if v < minimum:
        raise validation(f"{field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=0):
    v = body.get(field, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"{field} must be an integer")
    if v < minimum:
        raise validation(f"{field} must be >= {minimum}")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise validation(f"{field} must be a boolean")
    return v

"""Authentication and RBAC per PRD 2.1 / scaffold validations priorities 1-4.

Headers: X-User-ID + X-User-Role. Six declared roles. LabOperator's X-User-ID
is the id of the acting account (entity-backed identity); all other roles are
opaque operator identifiers.
"""

from flask import request

from errors import unauthenticated, forbidden

ROLES = {
    "PlatformAdmin",
    "AccountManager",
    "FinanceAdmin",
    "FieldServiceEngineer",
    "SupplyPlanner",
    "LabOperator",
}


def require_roles(*roles):
    """Priority 1 (headers/role validity -> 401) then priority 2 (endpoint
    role membership -> 403). Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or not role.strip():
        raise unauthenticated()
    if role not in ROLES:
        raise unauthenticated("Unknown role value")
    if role not in roles:
        raise forbidden("Role %s is not admitted to this endpoint" % role)
    return uid, role


def require_action_role(role, action, action_role_map):
    """Priority 3: per-action role gate on multi-action endpoints -> 403.

    Only evaluated when the action names a known gate; invalid/missing actions
    fall through to request-shape validation (400).
    """
    required = action_role_map.get(action)
    if required is not None and role != required:
        raise forbidden("Role %s cannot perform action %s" % (role, action))


def require_ownership(condition):
    """Priority 4: LabOperator ownership -> 403 when the caller's X-User-ID is
    not the account that owns the target resource."""
    if not condition:
        raise forbidden("Resource belongs to a different account")

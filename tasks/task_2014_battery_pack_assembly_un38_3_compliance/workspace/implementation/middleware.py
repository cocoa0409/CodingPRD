"""Auth header extraction + role gate per PRD §2.1 and validation priorities 1-2.

Every request carries X-User-ID (opaque operator id) and X-User-Role (one of
the seven recognized designations). Missing/malformed headers ->
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). An authenticated operator
attempting an operation reserved for another role ->
ERR_INSUFFICIENT_PERMISSIONS (403)."""

from functools import wraps

from flask import request

from errors import err_missing_user_context, err_insufficient_permissions

ROLES = {
    "AssemblyLead",
    "QualityEngineer",
    "SafetyOfficer",
    "LogisticsCoordinator",
    "CarrierAgent",
    "CustomerService",
    "Any",
}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def current_actor():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not isinstance(role, str) or role not in ROLES:
        raise err_missing_user_context()
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err_missing_user_context()
    return Actor(user_id=user_id, role=role)


def require_roles(*roles):
    """Decorator: enforce auth headers (priority 1) then role membership (2).
    With no explicit roles, any authenticated role may proceed (read routes
    declared with roles: [Any])."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = current_actor()
            if roles and actor.role not in roles:
                raise err_insufficient_permissions(
                    "Role %s is not permitted for this endpoint" % actor.role
                )
            return fn(actor, *args, **kwargs)

        return wrapper

    return deco

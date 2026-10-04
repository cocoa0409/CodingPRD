"""Auth middleware: X-User-ID / X-User-Role extraction and role gating."""
from functools import wraps

from flask import request

from errors import err_unauthenticated, err_forbidden_role

DECLARED_ROLES = {
    "Anonymous",
    "PlatformAdmin",
    "LeagueOps",
    "Subscriber",
    "VenueManager",
    "SupportAgent",
    "ComplianceAuditor",
}

# Roles whose X-User-ID is the id of the acting Account (entity-backed).
ENTITY_BACKED_ROLES = {"Subscriber", "VenueManager"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthenticated()
    if role not in DECLARED_ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate then enforce role membership.

    The wrapped view receives `auth=(user_id, role)` as a keyword argument.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth = get_auth()
            if auth[1] not in allowed:
                raise err_forbidden_role()
            kwargs["auth"] = auth
            return fn(*args, **kwargs)
        return wrapper
    return decorator

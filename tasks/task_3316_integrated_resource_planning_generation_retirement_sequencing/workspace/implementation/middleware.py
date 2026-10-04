"""Auth middleware and shared helpers.

Header names come from SCAFFOLD.yaml §1.4 priority 1 and PRD §2.1:
  X-User-ID, X-User-Role
Roles come from SCAFFOLD.yaml §1.7.
"""

from functools import wraps
from typing import Iterable

from flask import request

from errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, raise_error


DECLARED_ROLES = {
    "UtilityPlanner",
    "Commissioner",
    "Intervener",
    "PublicCommenter",
    "PlatformAdmin",
}


def current_auth():
    """Return (user_id, role) after validating the two auth headers.

    Raises ERR_UNAUTHENTICATED when either header is missing or the role is
    not one of the five declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and role must be declared")
    return user_id, role


def require_roles(*allowed: Iterable[str]):
    """Decorator: enforce auth (priority 1) then RBAC role check (priority 2).

    View functions wrapped with this decorator receive (user_id, role) as
    their first two positional arguments, followed by any path parameters.
    """
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = current_auth()
            if role not in allowed_set:
                raise_error(ERR_FORBIDDEN, f"Role {role} not permitted for this endpoint")
            return fn(user_id, role, *args, **kwargs)
        return wrapper

    return decorator

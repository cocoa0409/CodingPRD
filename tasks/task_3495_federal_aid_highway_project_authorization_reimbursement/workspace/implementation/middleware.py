"""Auth middleware: X-User-Role / X-User-ID extraction and RBAC (PRD §2.1)."""
import functools

from flask import request

from errors import err

ROLES = (
    "PlatformAdmin",
    "StateDOTPlanner",
    "StateDOTEngineer",
    "FHWADivisionAdmin",
    "FHWAReviewer",
)
ALL_ROLES = ROLES


def require_roles(*roles):
    """Decorator enforcing validation priorities 1 (ERR_UNAUTHENTICATED) and
    2 (ERR_FORBIDDEN). Injects user_id / user_role kwargs into the view."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role is None or role not in ROLES:
                raise err(
                    "ERR_UNAUTHENTICATED",
                    "X-User-Role header missing or names no declared role",
                )
            if role not in roles:
                raise err(
                    "ERR_FORBIDDEN",
                    "Caller role is not in the endpoint's roles list",
                )
            kwargs["user_id"] = request.headers.get("X-User-ID")
            kwargs["user_role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return deco

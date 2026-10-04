"""Auth middleware per PRD 2.1 / SCAFFOLD 1.4 priorities 1-2.

Every request (all endpoints under /franchise-system) requires:
  X-User-ID   -- present and non-empty (blank after strip -> error)
  X-User-Role -- present and non-empty

The four recognized roles are: FranchisorAdmin, FranchiseFinance, Operator,
CoopManager. An unrecognized role fails every endpoint's role check with
ERR_INSUFFICIENT_PERMISSIONS (403).
"""

from functools import wraps

from flask import request

from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ApiError,
)

ROLES = {"FranchisorAdmin", "FranchiseFinance", "Operator", "CoopManager"}


def current_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return uid, role


def require_roles(*allowed):
    """Decorator enforcing auth header presence (400) then role check (403)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = current_user()
            if uid is None or not str(uid).strip():
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    400,
                    "X-User-ID header is missing or blank",
                )
            if role is None or not str(role).strip():
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    400,
                    "X-User-Role header is missing or blank",
                )
            if role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    f"Role {role} is not permitted for this endpoint",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator

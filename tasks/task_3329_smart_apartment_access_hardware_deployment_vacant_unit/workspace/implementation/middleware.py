"""Auth header extraction and RBAC enforcement (PRD 2.1, 2.12 priorities 1-2)."""

from functools import wraps

from flask import request

from errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, ApiError

RECOGNIZED_ROLES = (
    "PlatformAdmin",
    "PropertyManager",
    "HardwareTechnician",
    "MaintenanceTechnician",
    "LeasingAgent",
    "Resident",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_resident(self):
        return self.role == "Resident"

    def __repr__(self):
        return "Caller(%r, %r)" % (self.user_id, self.role)


def current_caller():
    """Priority 1: both headers present and the role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Both X-User-ID and X-User-Role headers are required",
        )
    if role not in RECOGNIZED_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Unrecognized role: %s" % role)
    return Caller(user_id, role)


def require_roles(*roles):
    """Priority 2: the calling role must be permitted for this operation."""

    def decorator(handler):
        @wraps(handler)
        def wrapper(*args, **kwargs):
            caller = current_caller()
            if roles and caller.role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN,
                    "Role %s is not permitted for this operation" % caller.role,
                )
            return handler(*args, caller=caller, **kwargs)

        return wrapper

    return decorator
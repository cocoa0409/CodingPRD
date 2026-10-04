"""Auth middleware: X-User-ID / X-User-Role header extraction and role gating."""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = {
    "StudyAdmin",
    "MethodologyLead",
    "FieldOps",
    "AwardsOfficer",
    "LicensingManager",
    "ClientUser",
    "PressUser",
}

ALL_ROLES = (
    "StudyAdmin",
    "MethodologyLead",
    "FieldOps",
    "AwardsOfficer",
    "LicensingManager",
    "ClientUser",
    "PressUser",
)

OPS_READ_ROLES = (
    "StudyAdmin",
    "MethodologyLead",
    "FieldOps",
    "AwardsOfficer",
    "LicensingManager",
)


def require(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED", "Missing X-User-ID / X-User-Role, or role is not declared")
            if role not in roles:
                fail("ERR_FORBIDDEN", "Role is not authorized for this endpoint")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco

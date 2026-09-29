"""Authentication, RBAC and scope enforcement (PRD 2.1, rungs 1, 2 and 4)."""
import functools

from flask import request

from errors import ApiError

ROLES = (
    "DistrictAdmin",
    "PlacementCoordinator",
    "HomeSchoolCounselor",
    "AltEdTeacher",
    "Registrar",
    "SupportProviderStaff",
)

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"


class Ctx(object):
    __slots__ = ("uid", "role")

    def __init__(self, uid, role):
        self.uid = uid
        self.role = role


def endpoint(*roles):
    """Decorator applying rung 1 (authentication) then rung 2 (authorization)."""
    allowed = set(roles)

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get(HDR_USER)
            role = request.headers.get(HDR_ROLE)
            if uid is None or role is None or uid == "" or role == "":
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "X-User-ID and X-User-Role headers are required",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "role %s may not call this endpoint" % role,
                )
            return fn(Ctx(uid, role), *args, **kwargs)

        return wrapper

    return deco


# ---- scope helpers ----------------------------------------------------
def scope_center(ctx, center_id):
    if ctx.role == "PlacementCoordinator" and ctx.uid != center_id:
        raise ApiError(
            "ERR_FORBIDDEN_CENTER_SCOPE",
            "coordinator may only act inside its own center",
        )


def scope_school(ctx, home_school_id):
    if ctx.role == "HomeSchoolCounselor" and ctx.uid != home_school_id:
        raise ApiError(
            "ERR_FORBIDDEN_SCHOOL_SCOPE",
            "counselor may only act on its own school's students",
        )


def scope_provider(ctx, support_provider_id):
    if ctx.role == "SupportProviderStaff" and ctx.uid != support_provider_id:
        raise ApiError(
            "ERR_FORBIDDEN_PROVIDER_SCOPE",
            "provider may only act on its own support sessions",
        )

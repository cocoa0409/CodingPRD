"""Auth header extraction and per-endpoint role enforcement."""

from functools import wraps

from flask import request, g

from errors import ApiError

ROLES = {
    "NationalAdmin",
    "ReferralSource",
    "MedicalProvider",
    "EligibilityReviewer",
    "Volunteer",
    "WishCoordinator",
    "InKindOfficer",
    "ChapterDirector",
    "NationalDirector",
}


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED", 401,
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE", 403,
                    "Role %s is not authorized for this endpoint" % role,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco

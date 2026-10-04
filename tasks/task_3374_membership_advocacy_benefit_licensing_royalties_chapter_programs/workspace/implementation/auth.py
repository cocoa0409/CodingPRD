"""Authentication and role authorization (validation rungs 1-2).

Every endpoint requires X-User-ID and X-User-Role. The role must be one of
the ten declared roles and must be listed for the endpoint.
"""

from flask import request

from util import ApiError

ROLES = {
    "PlatformAdmin",
    "MemberServicesAgent",
    "Member",
    "ProviderManager",
    "GovernanceOfficer",
    "OversightAnalyst",
    "FinanceController",
    "StandardsReviewer",
    "ChapterCoordinator",
    "AdvocacyDirector",
}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_roles(*roles):
    user_id, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role %s is not permitted for this endpoint" % role)
    return user_id, role


def forbidden(message):
    raise ApiError("ERR_FORBIDDEN", 403, message)

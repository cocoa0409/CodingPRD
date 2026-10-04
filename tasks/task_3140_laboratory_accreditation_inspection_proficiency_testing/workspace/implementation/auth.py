from flask import request

from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "AccreditationOfficer",
    "LaboratoryDirector",
    "PTCoordinator",
    "Inspector",
}


def require_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid X-User-ID / X-User-Role headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return user_id, role

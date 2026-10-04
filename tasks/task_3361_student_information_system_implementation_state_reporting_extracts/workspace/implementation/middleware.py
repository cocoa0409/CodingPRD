"""Auth context extraction (pipeline stage 1) and role checks (stage 3)."""
from flask import request

from errors import ApiError

ROLES = {"PlatformAdmin", "DistrictAdmin", "Registrar", "StateReporter", "PortalUser"}

# The four operator roles share all GET list/detail endpoints except the
# portal-account detail, which is DistrictAdmin + PortalUser only.
READERS = {"PlatformAdmin", "DistrictAdmin", "Registrar", "StateReporter"}


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            400,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")

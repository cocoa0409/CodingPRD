"""Auth middleware per PRD 2.1: X-User-ID + X-User-Role headers."""
from flask import request

from errors import err_missing_headers, err_permissions

ROLES = {
    "PlatformAdmin",
    "ComplianceOfficer",
    "Recorder",
    "MedicalScreener",
    "Phlebotomist",
}


class UserContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_auth():
    """Extract and validate the user context headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        not user_id
        or not isinstance(user_id, str)
        or not user_id.strip()
        or not role
        or not isinstance(role, str)
        or role.strip() not in ROLES
    ):
        raise err_missing_headers()
    return UserContext(user_id.strip(), role.strip())


def require_roles(*allowed):
    """Validate headers, then role authorization (validation priorities 1 and 2)."""
    ctx = get_auth()
    if ctx.role not in allowed:
        raise err_permissions()
    return ctx


def get_body():
    """Return the JSON request body as a dict; {} when absent; error when malformed."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise _invalid()
    if not isinstance(data, dict):
        raise _invalid()
    return data


def _invalid():
    from errors import err_invalid_request
    return err_invalid_request("request body must be a JSON object")

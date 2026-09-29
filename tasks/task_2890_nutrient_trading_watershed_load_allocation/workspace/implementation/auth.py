"""Authentication (priority 1) and endpoint role authorization (priority 2)."""
from flask import g, request

from errors import ApiError

ROLES = (
    "ProgramAdministrator",
    "TmdlAnalyst",
    "PermitWriter",
    "Permittee",
    "Producer",
    "PracticeVerifier",
    "RegistryAdministrator",
)

ALL_ROLES = list(ROLES)


def authenticate():
    """Validate X-User-ID / X-User-Role; returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*roles):
    """Authenticate, then enforce the endpoint's authorized-role list."""
    user_id, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role

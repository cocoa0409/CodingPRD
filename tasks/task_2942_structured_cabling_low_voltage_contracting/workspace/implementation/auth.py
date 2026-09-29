"""PRD 2.1 / 2.8 steps 1-2 — crew identity headers then endpoint authorization."""

from functools import wraps

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PROJECT_MANAGER = "ProjectManager"
DESIGN_ENGINEER = "DesignEngineer"
INSTALLER = "Installer"
TEST_TECHNICIAN = "TestTechnician"
CERTIFIER = "Certifier"
MANUFACTURER_AGENT = "ManufacturerAgent"
CLIENT = "Client"

ROLES = (
    PROJECT_MANAGER,
    DESIGN_ENGINEER,
    INSTALLER,
    TEST_TECHNICIAN,
    CERTIFIER,
    MANUFACTURER_AGENT,
    CLIENT,
)

ALL_ROLES = ROLES


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not one of the seven declared roles.")
    return user_id, role


def require(*roles):
    """Screening step 1 (authentication) then step 2 (authorization)."""
    allowed = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not authorized for this endpoint." % role,
                )
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator

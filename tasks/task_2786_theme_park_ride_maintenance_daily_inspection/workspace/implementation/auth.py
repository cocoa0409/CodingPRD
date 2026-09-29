"""Request authentication and role authorisation (PRD 2.1, ladder steps 1-2)."""

from functools import wraps

from flask import g, request

from errors import fail, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

PARK_OPS_ADMIN = "ParkOpsAdmin"
MAINTENANCE_MANAGER = "MaintenanceManager"
MAINTENANCE_TECHNICIAN = "MaintenanceTechnician"
QUALIFIED_INSPECTOR = "QualifiedInspector"
SAFETY_OFFICER = "SafetyOfficer"
RIDE_OPERATOR = "RideOperator"

ALL_ROLES = (
    PARK_OPS_ADMIN,
    MAINTENANCE_MANAGER,
    MAINTENANCE_TECHNICIAN,
    QUALIFIED_INSPECTOR,
    SAFETY_OFFICER,
    RIDE_OPERATOR,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def _authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip():
        fail(ERR_UNAUTHENTICATED, "X-User-ID header is required.")
    if role is None or not str(role).strip():
        fail(ERR_UNAUTHENTICATED, "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ALL_ROLES:
        fail(ERR_UNAUTHENTICATED, "X-User-Role does not name a recognised role.")
    g.user_id = str(user_id).strip()
    g.role = role


def require_roles(*roles):
    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in allowed:
                fail(ERR_UNAUTHORIZED,
                     "Role %s may not call this endpoint." % g.role)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def any_role(view):
    return require_roles(*ALL_ROLES)(view)


def user_id():
    return g.user_id

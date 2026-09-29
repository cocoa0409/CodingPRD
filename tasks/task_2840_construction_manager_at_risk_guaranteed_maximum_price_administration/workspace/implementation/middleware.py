"""Authentication and role gating (PRD 2.1)."""
import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PROGRAM_ADMIN = "ProgramAdmin"
CONSTRUCTION_MANAGER = "ConstructionManager"
PROCUREMENT_OFFICER = "ProcurementOfficer"
OWNER_REPRESENTATIVE = "OwnerRepresentative"
INDEPENDENT_AUDITOR = "IndependentAuditor"

ALL_ROLES = (
    PROGRAM_ADMIN,
    CONSTRUCTION_MANAGER,
    PROCUREMENT_OFFICER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
)


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "missing %s header" % USER_ID_HEADER)
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "missing %s header" % USER_ROLE_HEADER)
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unrecognized role '%s'" % role)
    g.user_id = str(user_id).strip()
    g.user_role = role
    return g.user_id, g.user_role


def require_action_role(*allowed):
    """Action level authorization (PRD 2.11 step 3)."""
    if g.user_role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "role %s may not perform this action" % g.user_role,
        )


def endpoint(*allowed_roles):
    """Authenticate, then apply the endpoint level role gate."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if allowed_roles and g.user_role not in allowed_roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "role %s may not call this endpoint" % g.user_role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator

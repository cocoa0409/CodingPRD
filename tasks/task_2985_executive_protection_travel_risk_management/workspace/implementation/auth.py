"""Authentication, role authorisation and Executive ownership -- PRD 2.1, 2.11."""

import functools

from flask import g, request

from errors import ApiError

# PRD 2.1: the six roles, spelled exactly as shown.
ROLE_SECURITY_ANALYST = "SecurityAnalyst"
ROLE_PROTECTION_MANAGER = "ProtectionManager"
ROLE_SECURITY_DIRECTOR = "SecurityDirector"
ROLE_EXECUTIVE = "Executive"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_SYSTEM_OPERATOR = "SystemOperator"

DECLARED_ROLES = (
    ROLE_SECURITY_ANALYST,
    ROLE_PROTECTION_MANAGER,
    ROLE_SECURITY_DIRECTOR,
    ROLE_EXECUTIVE,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SYSTEM_OPERATOR,
)

# PRD 2.1: opaque operator identifiers, never compared to any entity's id.
OPAQUE_ROLES = (ROLE_COMPLIANCE_OFFICER, ROLE_SYSTEM_OPERATOR)


def authenticate():
    """PRD 2.1: header validation happens before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in DECLARED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(*roles):
    """Bind an endpoint's authorised role list (PRD section 4)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                raise ApiError("ERR_UNAUTHORIZED_ROLE")
            return fn(*args, **kwargs)

        wrapper.authorised_roles = roles
        return wrapper

    return decorator


def acting_id():
    return g.user_id


def acting_role():
    return g.role


def is_executive_caller():
    return g.role == ROLE_EXECUTIVE


def require_executive_owns(executive_id):
    """PRD 2.1: ownership narrowing applies specifically to Executive callers."""
    if is_executive_caller() and g.user_id != executive_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def compares_to_staff_rows():
    """True when X-User-ID is a SecurityStaff id (PRD 2.1)."""
    return g.role in (
        ROLE_SECURITY_ANALYST,
        ROLE_PROTECTION_MANAGER,
        ROLE_SECURITY_DIRECTOR,
    )

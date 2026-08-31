"""Authentication, RBAC and ownership (PRD 2.1 and 2.8 steps 1-3)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = ("FundAdministrator", "ContributingEmployer", "Trustee", "PayrollAuditor", "Actuary")
ALL_ROLES = list(ROLES)
READ_ROLES = list(ROLES)


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_employer_id():
    return g.user_id if g.role == "ContributingEmployer" else None


def require_owner_employer(employer_id):
    """Ownership check for entity-backed ContributingEmployer actors."""
    if g.role == "ContributingEmployer" and g.user_id != employer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

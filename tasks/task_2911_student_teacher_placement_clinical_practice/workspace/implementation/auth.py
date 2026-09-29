"""Authentication, RBAC and ownership (PRD 2.1, ladder rungs 1-4)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "PlacementCoordinator",
    "CredentialAnalyst",
    "SupervisionLead",
    "AssessmentScorer",
    "UniversitySupervisorUser",
    "CandidateUser",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role '%s' is not a recognised role." % role)
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not call this endpoint." % role,
        )


def endpoint(roles):
    """Wrap a handler with rungs 1-3 and expose the principal on flask.g."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            authorize(role, roles)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def user_id():
    return g.user_id


def role():
    return g.role


def require_owner(expected_id):
    if user_id() != expected_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting principal does not own this resource.")

"""Operator identity and role authority (PRD sections 2.1, 2.8 rules 1 and 2)."""
import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

EVIDENCE_TECHNICIAN = "EvidenceTechnician"
CASE_MANAGER = "CaseManager"
ANALYST = "Analyst"
QUALITY_MANAGER = "QualityManager"
LAB_DIRECTOR = "LabDirector"

ROLES = (
    EVIDENCE_TECHNICIAN,
    CASE_MANAGER,
    ANALYST,
    QUALITY_MANAGER,
    LAB_DIRECTOR,
)


def authenticate(allowed_roles):
    """Rule 1 then rule 2. Authorisation outranks payload validity."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both %s and %s headers are required and must be non-empty."
            % (USER_ID_HEADER, USER_ROLE_HEADER),
        )
    if role not in ROLES or role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role '%s' is not authorised for this endpoint." % role,
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(*allowed_roles):
    """Bind an endpoint to its authorised roles."""
    roles = tuple(allowed_roles)

    def decorate(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            authenticate(roles)
            return view(*args, **kwargs)

        return wrapped

    return decorate

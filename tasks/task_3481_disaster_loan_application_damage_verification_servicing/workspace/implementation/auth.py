"""Auth middleware (PRD 2.1): header presence, role authorization, ownership."""

from functools import wraps

from flask import g, request

from errors import ApiError

VALID_ROLES = {
    "Anonymous",
    "Applicant",
    "LoanOfficer",
    "LossVerifier",
    "LoanApprover",
    "ServicingAgent",
    "GrantCoordinator",
    "SystemAdmin",
}


def require_roles(*roles):
    """Guard: X-User-ID / X-User-Role present and non-empty (401), role allowed (403)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or role is None or uid.strip() == "" or role.strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or empty X-User-ID / X-User-Role")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", 403, "role %s is not permitted on this endpoint" % role)
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def check_owner(applicant_id):
    """Entity-backed ownership: an Applicant-role caller may only touch own resources."""
    if g.role == "Applicant" and g.user_id != applicant_id:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "applicant does not own this resource")

"""Authentication, role authorisation and ownership (rungs 1, 2 and 4)."""

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_GROWER = "Grower"
ROLE_VERIFIER = "Verifier"
ROLE_REGISTRY_OFFICER = "RegistryOfficer"

ROLES = (ROLE_PROGRAM_ADMIN, ROLE_GROWER, ROLE_VERIFIER, ROLE_REGISTRY_OFFICER)


def authenticate():
    """Rung 1 -- identity headers present, non-empty, role recognised."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The %s header is missing or empty." % USER_ID_HEADER)
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The %s header is missing or empty." % USER_ROLE_HEADER)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "The %s header carries an unrecognised role." % USER_ROLE_HEADER)
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed_roles):
    """Rungs 1 and 2 together -- returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id, role


def require_grower_owner(grower_id):
    """Rung 4 -- a Grower caller may only reach its own subtree."""
    if g.get("role") == ROLE_GROWER and g.get("user_id") != grower_id:
        raise ApiError("ERR_RESOURCE_NOT_OWNED", "The caller does not own the addressed resource.")


def require_verifier_owner(verification_body_id):
    """Rung 4 -- a Verifier caller may only reach its own verifications."""
    if g.get("role") == ROLE_VERIFIER and g.get("user_id") != verification_body_id:
        raise ApiError("ERR_RESOURCE_NOT_OWNED", "The caller does not own the addressed resource.")


def caller():
    return g.get("user_id"), g.get("role")

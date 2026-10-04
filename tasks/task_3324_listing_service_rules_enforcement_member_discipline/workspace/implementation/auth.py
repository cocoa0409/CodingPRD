"""Auth middleware per PRD §2.1: X-User-ID / X-User-Role headers."""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_MEMBER_MISMATCH

ROLES = ("AssociationStaff", "Member", "GrievanceMember", "HearingPanelist")


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role).

    Priority 1: missing/unknown headers -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role or X-User-ID")
    return user_id, role


def require_roles(*roles):
    """Priority 2: role permitted for the endpoint, else ERR_FORBIDDEN (403)."""
    user_id, role = get_auth()
    if role not in roles:
        raise_err(ERR_FORBIDDEN, "Role %s not permitted for this endpoint" % role)
    return user_id, role


def require_member_actor(user_id, expected_member_id):
    """Right role but wrong member id -> ERR_MEMBER_MISMATCH (403)."""
    if user_id != expected_member_id:
        raise_err(ERR_MEMBER_MISMATCH,
                  "Member %s may not act on a resource owned by member %s"
                  % (user_id, expected_member_id))

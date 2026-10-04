"""Auth middleware (PRD §2.1, validation ladder rungs 1-2 and 4).

Headers: X-User-ID and X-User-Role. ChannelRep / Assembler are entity-backed
(X-User-ID is the id of the ChannelAccount / Assembler); PlannerAdmin,
ServiceAgent and AppUser identities are opaque.
"""

from flask import request

from constants import ALL_ROLES
from errors import api_error


def authenticate():
    """Rung 1: both headers present and role is one of the five declared roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise api_error("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required")
    return user_id, role


def require_role(role, allowed_roles):
    """Rung 2 (endpoint level): acting role must be listed for the endpoint."""
    if role not in allowed_roles:
        raise api_error("ERR_UNAUTHORIZED_ROLE", "role %s is not permitted for this endpoint" % role)


def check_action_role(role, action, action_roles):
    """Rung 2 (action level) for action endpoints. Unknown actions cannot be
    role-checked; they fall through to body validation (rung 6) and are
    reported as ERR_VALIDATION by the caller."""
    if action in action_roles and role not in action_roles[action]:
        raise api_error(
            "ERR_UNAUTHORIZED_ROLE",
            "role %s is not permitted for action %s" % (role, action),
        )


def check_ownership(user_id, owner_id):
    """Rung 4: entity-backed caller must match the resource's owner id."""
    if user_id != owner_id:
        raise api_error("ERR_FORBIDDEN_OWNERSHIP", "resource is owned by a different account")

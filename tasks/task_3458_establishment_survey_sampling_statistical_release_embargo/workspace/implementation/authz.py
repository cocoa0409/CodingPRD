"""Authentication and authorization per PRD 2.1 and validation stages 1-2.

Every request carries X-User-ID and X-User-Role. Stage 1: both headers present
and the role is one of the eight declared roles, else ERR_UNAUTHENTICATED.
Stage 2: the role is permitted on the endpoint / on the named action of an
action-style endpoint; entity-backed ownership (Respondent -> establishment_id,
AccreditedMedia -> grant's media_outlet_id) else ERR_FORBIDDEN.
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN
from store import ROLES


def get_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_UNAUTHENTICATED,
            "X-User-ID and a declared X-User-Role header are required",
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"role {role} is not permitted on this endpoint")


def require_action_role(role, action, action_roles):
    """Per-action role split inside advance/lifecycle endpoints (PRD 2.1)."""
    allowed = action_roles.get(action)
    if allowed is not None and role not in allowed:
        raise_err(ERR_FORBIDDEN, f"role {role} may not perform action {action}")


def require_ownership(user_id, owner_id, what="resource"):
    if user_id != owner_id:
        raise_err(ERR_FORBIDDEN, f"caller does not own the targeted {what}")

"""Authentication and role authorisation (PRD 2.1, order-of-evaluation steps 1-2)."""
from flask import g, request

from constants import ALL_ROLES
from errors import ApiError


def authenticate():
    """Step 1.  Both headers present and X-User-Role one of the six roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def authorize(allowed_roles):
    """Step 2.  The role must be listed on the endpoint (or on the action)."""
    if g.user_role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def authorize_action(endpoint_roles, action_roles, action):
    """Multi-action endpoints: the role check is evaluated against the action.

    When the requested action is not a declared member we cannot resolve an
    action-specific role list, so the endpoint-level list governs and the shape
    check (step 4) reports the undeclared action.
    """
    if action in action_roles:
        authorize(action_roles[action])
    else:
        authorize(endpoint_roles)


def current_user():
    return g.user_id


def current_role():
    return g.user_role

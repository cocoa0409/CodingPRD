"""Authentication and RBAC (PRD 2.1; validations priority 1 and 2)."""
from flask import g, request

from db import ROLES
from errors import fail


def authenticate():
    """Priority 1: both headers present and X-User-Role a recognised role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "valid X-User-ID and X-User-Role headers are required")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Priority 2: the acting role must appear in the endpoint's declared roles list."""
    if allowed and g.role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % g.role)


def actor():
    return g.user_id


def check_sod(recorded_user_id):
    """Priority 13: the actor must differ from the recorded prior actor.

    The literal 'SYSTEM' requester never collides with a real operator.
    """
    from db import SYSTEM_ACTOR
    if recorded_user_id is None or recorded_user_id == SYSTEM_ACTOR:
        return
    if recorded_user_id == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the acting user may not perform this step after performing the preceding one")

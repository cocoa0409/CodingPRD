"""Authentication, role authorisation and actor resolution (PRD 2.1)."""
from flask import request

import db
from errors import ApiError

MOUNTAIN_OPS_DIRECTOR = "MountainOpsDirector"
SNOWMAKING_SUPERVISOR = "SnowmakingSupervisor"
GROOMING_LEAD = "GroomingLead"
LIFT_OPS_MANAGER = "LiftOpsManager"
PATROLLER = "Patroller"
GUEST_SERVICES_AGENT = "GuestServicesAgent"

ALL_ROLES = (
    MOUNTAIN_OPS_DIRECTOR,
    SNOWMAKING_SUPERVISOR,
    GROOMING_LEAD,
    LIFT_OPS_MANAGER,
    PATROLLER,
    GUEST_SERVICES_AGENT,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def auth(*allowed_roles):
    """Priority 1 then 2: authenticate, then authorise the role.

    Returns (user_id, role).
    """
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def acting_patroller(*allowed_roles):
    """Patroller-owned action: X-User-ID must resolve to a Patroller row.

    PRD 2.1 - a Patroller-owned action whose X-User-ID does not resolve to an
    existing patroller row is rejected with ERR_UNAUTHORIZED (403).
    """
    user_id, role = auth(*allowed_roles)
    patroller = db.store.patrollers.get(user_id)
    if patroller is None:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role, patroller

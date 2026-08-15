"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import ApiError, raise_error, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ALL_ROLES = {"OperationsManager", "Pilot", "Customer", "ChaseCrewLead", "Anonymous"}
ALL_READ_ROLES = ["OperationsManager", "Pilot", "Customer", "ChaseCrewLead"]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present; role is a declared role."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and role must be declared")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: authentication, then role membership on the endpoint."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_UNAUTHORIZED,
                    f"role {caller.role} is not authorized for this endpoint")
    return caller


def peek_event_type():
    """Silently parse the JSON body and return its event_type (or None).

    Used at priority 2 on shared events endpoints: a request whose event_type
    belongs to a different role's slice is ERR_UNAUTHORIZED before any
    existence/body-shape check runs.
    """
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        et = body.get("event_type")
        if isinstance(et, str):
            return et
    return None


def check_event_slice(caller: Caller, event_type, role_slices):
    """Priority 2 (shared events endpoints): the event_type must belong to the
    acting role's slice. Unknown/absent event_type is left for priority-4 body
    validation (ERR_INVALID_REQUEST)."""
    if event_type is None:
        return
    known = set()
    for evs in role_slices.values():
        known |= set(evs)
    if event_type not in known:
        return
    if event_type not in role_slices.get(caller.role, set()):
        raise_error(ERR_UNAUTHORIZED,
                    f"event_type {event_type} is not permitted for role {caller.role}")

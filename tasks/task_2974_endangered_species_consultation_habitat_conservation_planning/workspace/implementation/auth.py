"""Rungs 1, 2, 3 and 5 of the validation ladder: identity, role, ownership."""
from flask import request

import store
from errors import ApiError

ROLES = ("Proponent", "WildlifeAgency", "Auditor", "Anonymous")
NEEDS_USER_ID = ("Proponent", "WildlifeAgency")


class Caller(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def authenticate(allowed, presence_exempt=False):
    """Rung 1 (header presence), rung 2 (role is one of the declared four) and
    rung 3 (role permitted on this endpoint).

    `presence_exempt` is proponent self-registration, which PRD 2.1 exempts
    from the header-presence check altogether and reaches as `Anonymous`.
    """
    raw_role = request.headers.get("X-User-Role")
    raw_user = request.headers.get("X-User-ID")

    blank_role = raw_role is None or raw_role.strip() == ""

    if presence_exempt:
        role = "Anonymous" if blank_role else raw_role
    else:
        if blank_role:
            raise ApiError("ERR_UNAUTHENTICATED")
        role = raw_role

    # Rung 2 -- an unrecognised role is unauthenticated, never forbidden.
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")

    if not presence_exempt and role in NEEDS_USER_ID:
        if raw_user is None or raw_user == "":
            raise ApiError("ERR_UNAUTHENTICATED")

    # Rung 3.
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    return Caller(role, raw_user)


# ------------------------------------------------------------- ownership ----


def require_identity(caller):
    """A `Proponent` caller whose X-User-ID names no Proponent row fails
    ownership, on every proponent-reachable endpoint (PRD 2.1)."""
    if caller.role != "Proponent":
        return None
    row = store.get("proponents", caller.user_id)
    if row is None:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return row


def require_owner(caller, owner_id):
    """Rung 5.  `owner_id` is the Proponent.id the target resource resolves to,
    or None when the resource has no owner (species, habitat units, banks)."""
    require_identity(caller)
    if caller.role != "Proponent":
        return
    if owner_id is not None and owner_id != caller.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def owner_of_action(action):
    return action.get("proponent_id")


def owner_of_determination(row):
    action = store.get("actions", row.get("project_action_id"))
    return owner_of_action(action) if action else None


def owner_of_consultation(row):
    action = store.get("actions", row.get("project_action_id"))
    return owner_of_action(action) if action else None


def owner_of_plan(row):
    action = store.get("actions", row.get("project_action_id"))
    return owner_of_action(action) if action else None


def owner_of_permit(row):
    plan = store.get("plans", row.get("hcp_id"))
    return owner_of_plan(plan) if plan else None


def owner_of_report(row):
    permit = store.get("permits", row.get("permit_id"))
    return owner_of_permit(permit) if permit else None


def owner_of_event(row):
    plan = store.get("plans", row.get("hcp_id"))
    return owner_of_plan(plan) if plan else None

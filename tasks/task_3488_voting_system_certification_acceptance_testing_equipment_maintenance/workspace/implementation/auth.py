"""Authentication / authorization helpers (PRD 2.1, pipeline priorities 1-2).

Headers: X-User-ID + X-User-Role on every request. Seven declared roles.
Entity-backed roles: LabAgent (X-User-ID == TestLaboratory.id) and
ElectionOfficial (X-User-ID == ElectionOfficial.id); the rest are opaque.
"""
from flask import request

from errors import err_forbidden_ownership, err_unauthenticated, err_unauthorized, raise_err
from store import db

ROLES = {
    "PlatformAdmin",
    "CertificationAuthority",
    "VendorRep",
    "LabAgent",
    "ElectionOfficial",
    "Auditor",
    "PublicRequester",
}


def auth_context():
    """Priority 1: both headers present, role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err_unauthenticated()
    return uid, role


def require_role(role, allowed):
    """Priority 2 (endpoint level): role appears in the endpoint's role list."""
    if role not in allowed:
        err_unauthorized()


def peek_to_state():
    """Best-effort read of the body's to_state for the priority-2 actor check.

    Transition-level RBAC is evaluated before path resolution; an unreadable
    or to_state-less body defers to the priority-4 body check.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        ts = data.get("to_state")
        if isinstance(ts, str):
            return ts
    return None


def require_transition_actor(role, to_state, actor_map):
    """Priority 2 (transition level): role is the declared actor of to_state.

    actor_map contains only to_states with human actors; system-only targets
    (e.g. IN_MAINTENANCE, EXPIRED) are absent and fall through to the
    state-legality check, which rejects them with ERR_INVALID_STATE.
    """
    if to_state is None:
        return
    actors = actor_map.get(to_state)
    if actors and role not in actors:
        err_unauthorized("role is not the declared actor of transition %s" % to_state)


def require_acting_official(uid, jurisdiction_id):
    """Priority 6: entity-backed ownership for ElectionOfficial actors.

    The acting official must resolve, belong to the target jurisdiction, and
    be ACTIVE (scaffold ElectionOfficial.status: 'ACTIVE officials may act;
    INACTIVE officials are refused').
    """
    official = db.election_officials.get(uid)
    if official is None:
        err_forbidden_ownership("acting election official does not resolve")
    if official["jurisdiction_id"] != jurisdiction_id:
        err_forbidden_ownership("official belongs to a different jurisdiction")
    if official["status"] != "ACTIVE":
        raise_err("ERR_OFFICIAL_INACTIVE", 422, "acting official is INACTIVE")
    return official

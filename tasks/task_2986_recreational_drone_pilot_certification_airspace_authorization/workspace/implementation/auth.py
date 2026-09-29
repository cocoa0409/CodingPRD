"""Rungs 1-3 of the precedence ladder: authentication, role admissibility,
pilot ownership (PRD 2.1, 2.11)."""

from flask import request

from errors import ApiError
from store import store

ROLES = (
    "Pilot",
    "ComplianceOfficer",
    "AirspaceAuthority",
    "SafetyReviewer",
    "WaiverApprover",
    "InvestigationOfficer",
)


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_pilot(self):
        return self.role == "Pilot"


def authenticate(allowed_roles):
    """Rung 1 then rung 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required")
    if not user_id.strip() or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-blank")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    return Caller(user_id, role)


def owner_of(row):
    """The id of the pilot who owns a row, or None when the row is unowned."""
    if row is None:
        return None
    kind = row.get("_kind")
    if kind == "pilots":
        return row["id"]
    if kind in ("knowledge_tests", "certifications", "authorizations", "waivers",
                "policies", "flights"):
        return row.get("pilot_id")
    if kind == "aircraft":
        return row.get("owner_pilot_id")
    if kind == "modules":
        return owner_of(store.get("aircraft", row.get("aircraft_id")))
    if kind == "safety_cases":
        return owner_of(store.get("waivers", row.get("waiver_id")))
    if kind in ("preflight_checks", "reports"):
        return owner_of(store.get("flights", row.get("flight_id")))
    return None


def check_owns(caller, row):
    """Rung 3 on the addressed resource.

    Only evaluable once the row has been resolved; an unresolved path id is
    left to rung 6.
    """
    if not caller.is_pilot or row is None:
        return
    owner = owner_of(row)
    if owner is not None and owner != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "resource belongs to another pilot")


def check_body_owner(caller, body):
    """Rung 3 on pilot_id / owner_pilot_id supplied in the body."""
    if not caller.is_pilot or not isinstance(body, dict):
        return
    for key in ("pilot_id", "owner_pilot_id"):
        value = body.get(key)
        if isinstance(value, str) and value != caller.user_id:
            raise ApiError("ERR_OWNERSHIP_VIOLATION",
                           "%s must be the acting pilot" % key)


def scope_to_owner(caller, rows):
    """A pilot may read only their own resources (PRD 2.1)."""
    if not caller.is_pilot:
        return rows
    out = []
    for row in rows:
        owner = owner_of(row)
        if owner is None or owner == caller.user_id:
            out.append(row)
    return out

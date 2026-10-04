"""Auth + RBAC (PRD §2.1, scaffold validations priorities 1, 2, 5).

Headers: X-User-Role (always), X-User-ID (required iff the role is
entity-backed). Entity-backed roles: LeadStateAG, ParticipatingStateAG,
StateLegislature. Opaque roles: CommitteeChair, DefendantCounsel,
FundAdministrator, ComplianceMonitor.
"""
from flask import request

import db
import errors

ROLES = (
    "CommitteeChair",
    "LeadStateAG",
    "ParticipatingStateAG",
    "DefendantCounsel",
    "FundAdministrator",
    "StateLegislature",
    "ComplianceMonitor",
)

ENTITY_BACKED = ("LeadStateAG", "ParticipatingStateAG", "StateLegislature")

ALL_ROLES = ROLES  # every GET endpoint is shared by all seven roles


def authenticate():
    """Rung 1: role header names a declared role; id present iff entity-backed."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise errors.unauthenticated()
    if role in ENTITY_BACKED and (user_id is None or user_id == ""):
        raise errors.unauthenticated("X-User-ID required for entity-backed role")
    return role, user_id


def require_roles(role, allowed):
    """Rung 2: caller role must be listed for the endpoint."""
    if role not in allowed:
        raise errors.unauthorized_role()


def require_own_office(participation_or_office_id, user_id):
    """Rung 5: X-User-ID must equal the target resource's state_office_id."""
    owner_id = (
        participation_or_office_id
        if isinstance(participation_or_office_id, str)
        else participation_or_office_id["state_office_id"]
    )
    if user_id != owner_id:
        raise errors.not_resource_owner()


def require_lead_active(investigation_id, office_id):
    """Rung 5 (lead-gated ops): caller office must hold a LEAD+ACTIVE
    participation in the relevant investigation."""
    for p in db.participations.values():
        if (
            p["investigation_id"] == investigation_id
            and p["state_office_id"] == office_id
            and p["status"] == "ACTIVE"
            and p["committee_role"] == "LEAD"
        ):
            return p
    raise errors.not_resource_owner(
        "Caller office holds no LEAD+ACTIVE participation in this investigation"
    )


def active_participation(investigation_id, office_id):
    for p in db.participations.values():
        if (
            p["investigation_id"] == investigation_id
            and p["state_office_id"] == office_id
            and p["status"] == "ACTIVE"
        ):
            return p
    return None

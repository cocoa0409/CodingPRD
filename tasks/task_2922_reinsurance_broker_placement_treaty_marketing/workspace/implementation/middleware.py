"""Authentication, actor resolution and role authorisation (PRD 2.1).

Priority ladder positions 1-4:
  1  ERR_MISSING_USER_ID   both headers must be present and non-blank
  2  ERR_UNKNOWN_USER      X-User-ID must resolve to a known actor
  3  ERR_UNAUTHORIZED      the role must appear in the endpoint's role list
  4  ERR_FOREIGN_RESOURCE  instance ownership on the seven counterparty writes
"""
from flask import request

import db
from errors import ApiError, fail

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
BROKER_PLACEMENT_LEAD = "BrokerPlacementLead"
BROKER_ACTUARY = "BrokerActuary"
BROKER_ACCOUNTANT = "BrokerAccountant"
COMPLIANCE_OFFICER = "ComplianceOfficer"
CEDENT_UNDERWRITER = "CedentUnderwriter"
REINSURER_UNDERWRITER = "ReinsurerUnderwriter"

ALL_ROLES = (
    PLATFORM_ADMIN,
    BROKER_PLACEMENT_LEAD,
    BROKER_ACTUARY,
    BROKER_ACCOUNTANT,
    COMPLIANCE_OFFICER,
    CEDENT_UNDERWRITER,
    REINSURER_UNDERWRITER,
)

# Broker/platform-side roles hold fixed opaque identities that are not tied to
# any persisted entity.
OPAQUE_ROLES = (
    PLATFORM_ADMIN,
    BROKER_PLACEMENT_LEAD,
    BROKER_ACTUARY,
    BROKER_ACCOUNTANT,
    COMPLIANCE_OFFICER,
)

OPAQUE_IDENTITIES = {
    "admin-1",
    "lead-1",
    "lead-2",
    "act-1",
    "acct-1",
    "acct-2",
    "compl-1",
}


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_cedent(self):
        return self.role == CEDENT_UNDERWRITER

    @property
    def is_reinsurer(self):
        return self.role == REINSURER_UNDERWRITER


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate():
    """Priorities 1 and 2."""
    raw_id = _header(HEADER_USER_ID)
    raw_role = _header(HEADER_USER_ROLE)
    if raw_id is None or raw_id.strip() == "":
        fail("ERR_MISSING_USER_ID", "X-User-ID header is required")
    if raw_role is None or raw_role.strip() == "":
        fail("ERR_MISSING_USER_ID", "X-User-Role header is required")
    user_id = raw_id
    role = raw_role

    if role in OPAQUE_ROLES:
        if user_id not in OPAQUE_IDENTITIES:
            fail("ERR_UNKNOWN_USER", "X-User-ID does not resolve to a known actor")
    elif role == CEDENT_UNDERWRITER:
        if user_id not in db.cedents:
            fail("ERR_UNKNOWN_USER", "X-User-ID is not the id of an existing cedent")
    elif role == REINSURER_UNDERWRITER:
        if user_id not in db.reinsurers:
            fail("ERR_UNKNOWN_USER", "X-User-ID is not the id of an existing reinsurer")
    else:
        # An unrecognised role still needs a resolvable identity before the
        # authorisation check at priority 3 can reject the role itself.
        known = (
            user_id in OPAQUE_IDENTITIES
            or user_id in db.cedents
            or user_id in db.reinsurers
        )
        if not known:
            fail("ERR_UNKNOWN_USER", "X-User-ID does not resolve to a known actor")
    return Actor(user_id, role)


def authorize(actor, roles):
    """Priority 3."""
    if actor.role not in roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % actor.role)
    return actor


def require(roles):
    """Authenticate then authorise in one step; returns the Actor."""
    actor = authenticate()
    return authorize(actor, roles)


def own_reinsurer(actor, reinsurer_id):
    """Priority 4 for reinsurer-scoped writes."""
    if actor.is_reinsurer and actor.user_id != reinsurer_id:
        fail("ERR_FOREIGN_RESOURCE", "resource belongs to another reinsurer")


def own_cedent(actor, cedent_id):
    """Priority 4 for cedent-scoped writes."""
    if actor.is_cedent and actor.user_id != cedent_id:
        fail("ERR_FOREIGN_RESOURCE", "resource belongs to another cedent")

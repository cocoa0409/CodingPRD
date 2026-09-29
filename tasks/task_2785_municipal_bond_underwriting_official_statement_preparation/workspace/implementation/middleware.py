"""Authentication, role authorisation, identity resolution and ownership.

Tiers 1, 2, 3 and 8 of the validation ladder (PRD 2.1, 2.5).
"""
from flask import request

import db
from errors import ApiError

ROLE_ISSUER_OFFICIAL = "IssuerOfficial"
ROLE_MUNICIPAL_ADVISOR = "MunicipalAdvisor"
ROLE_UNDERWRITER = "Underwriter"
ROLE_BOND_COUNSEL = "BondCounsel"
ROLE_RATING_ANALYST = "RatingAnalyst"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLES = [
    ROLE_ISSUER_OFFICIAL,
    ROLE_MUNICIPAL_ADVISOR,
    ROLE_UNDERWRITER,
    ROLE_BOND_COUNSEL,
    ROLE_RATING_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
]

MUNICIPAL_ADVISOR_FIRM_TYPES = ("MUNICIPAL_ADVISOR", "DUAL_REGISTERED")
UNDERWRITER_FIRM_TYPES = ("UNDERWRITER", "DUAL_REGISTERED")


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.firm = None
        self.issuer = None


def authenticate(allowed_roles):
    """Tier 1 authentication, tier 2 role authorisation, tier 3 identity resolution."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    actor = Actor(user_id, role)
    if role == ROLE_ISSUER_OFFICIAL:
        issuer = db.db.issuers.get(user_id)
        if issuer is None:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        actor.issuer = issuer
    elif role in (ROLE_MUNICIPAL_ADVISOR, ROLE_UNDERWRITER):
        firm = db.db.firms.get(user_id)
        if firm is None:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        if role == ROLE_MUNICIPAL_ADVISOR and firm["firm_type"] not in MUNICIPAL_ADVISOR_FIRM_TYPES:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        if role == ROLE_UNDERWRITER and firm["firm_type"] not in UNDERWRITER_FIRM_TYPES:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        actor.firm = firm
    return actor


def has_active_seat(deal_id, firm_id):
    for member in db.db.members.values():
        if (
            member["deal_id"] == deal_id
            and member["firm_id"] == firm_id
            and member["status"] == "ACTIVE"
        ):
            return True
    return False


def require_deal_ownership(actor, deal, adding_firm_id=None):
    """Tier 8: the acting principal must own the deal-scoped resource (PRD 2.1)."""
    if actor.role == ROLE_ISSUER_OFFICIAL:
        if deal["issuer_id"] != actor.user_id:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        return
    if actor.role == ROLE_MUNICIPAL_ADVISOR:
        if deal["municipal_advisor_firm_id"] != actor.user_id:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        return
    if actor.role == ROLE_UNDERWRITER:
        if has_active_seat(deal["id"], actor.user_id):
            return
        # Carve-out: an unseated underwriter may add its own firm to the syndicate.
        if adding_firm_id is not None and adding_firm_id == actor.user_id:
            return
        # Carve-out: a competitive sale has no pre-sale syndicate, so any firm
        # that is not suspended and whose firm_type admits Underwriter may act.
        if deal["sale_method"] == "COMPETITIVE":
            firm = db.db.firms.get(actor.user_id)
            if firm is not None and not firm["is_suspended"]:
                return
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    # BondCounsel, RatingAnalyst and ComplianceOfficer carry no deal ownership.
    return


def require_pinned_analyst(actor, engagement):
    """PRD 3.5: once pinned, only that analyst may act on the engagement."""
    pinned = engagement["assigned_analyst_user_id"]
    if pinned is not None and pinned != actor.user_id:
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")

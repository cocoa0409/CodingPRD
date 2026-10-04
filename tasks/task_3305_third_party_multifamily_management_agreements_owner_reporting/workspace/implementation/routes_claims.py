"""Routes: Claims and ClaimSettlements."""

from flask import Blueprint, request

import calc
from db import db, new_id, now_iso
from errors import (
    incident_outside_term,
    invalid_request,
    invalid_state_transition,
    reserve_outstanding,
    stale_version,
)
from middleware import (
    get_or_404,
    parse_iso,
    req_enum,
    req_int,
    req_iso,
    require_roles,
)
from response import body, ok_object, paginate

bp = Blueprint("claims", __name__)

GET_ROLES = ("PortfolioManager", "RiskOfficer", "OwnerRep", "PropertyAccountant")


def claim_out(c):
    return dict(c)


def settlement_out(s):
    return dict(s)


def _arg(name):
    return request.args.get(name)


@bp.post("/mgmt/properties/<propertyId>/claims")
def create_claim(propertyId):
    require_roles("RiskOfficer")
    get_or_404(db.properties, propertyId)
    data = body()
    claim_type = req_enum(data, "claim_type", ("RESIDENT_INCIDENT", "EMPLOYMENT"))
    reserved_amount_cents = req_int(data, "reserved_amount_cents")
    if reserved_amount_cents < 0:
        raise invalid_request("reserved_amount_cents must be non-negative")
    indemnified_by = req_enum(data, "indemnified_by", ("OWNER", "MANAGER", "SHARED"))
    incident_date = req_iso(data, "incident_date")
    now = now_iso()
    c = {
        "id": new_id(),
        "property_id": propertyId,
        "claim_type": claim_type,
        "reserved_amount_cents": reserved_amount_cents,
        "indemnified_by": indemnified_by,
        "incident_date": data["incident_date"],
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.claims[c["id"]] = c
    return ok_object(claim_out(c), status=201)


@bp.get("/mgmt/claims/<claimId>")
def get_claim(claimId):
    require_roles(*GET_ROLES)
    c = get_or_404(db.claims, claimId)
    return ok_object(claim_out(c))


@bp.get("/mgmt/properties/<propertyId>/claims")
def list_claims_for_property(propertyId):
    require_roles(*GET_ROLES)
    get_or_404(db.properties, propertyId)
    claim_type = _arg("claim_type")
    status = _arg("status")
    items = sorted(
        (c for c in db.claims.values() if c["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if claim_type is not None:
        items = [c for c in items if c["claim_type"] == claim_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([claim_out(c) for c in items])


@bp.get("/mgmt/claims")
def list_claims():
    require_roles(*GET_ROLES)
    property_id = _arg("property_id")
    claim_type = _arg("claim_type")
    status = _arg("status")
    items = sorted(db.claims.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [c for c in items if c["property_id"] == property_id]
    if claim_type is not None:
        items = [c for c in items if c["claim_type"] == claim_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([claim_out(c) for c in items])


@bp.post("/mgmt/claims/<claimId>/begin_review")
def begin_review(claimId):
    require_roles("RiskOfficer")
    c = get_or_404(db.claims, claimId)
    if c["status"] != "OPEN":
        raise invalid_state_transition("Claim must be OPEN to begin review")
    prop = db.properties[c["property_id"]]
    # Reserve: hold reserved amount against property cash
    prop["cash_available_cents"] = prop.get("cash_available_cents", 0) - c["reserved_amount_cents"]
    prop["updated_at"] = now_iso()
    prop["version"] += 1
    c["status"] = "UNDER_REVIEW"
    c["updated_at"] = now_iso()
    c["version"] += 1
    return ok_object(claim_out(c))


@bp.post("/mgmt/claims/<claimId>/settle")
def settle_claim(claimId):
    require_roles("RiskOfficer")
    c = get_or_404(db.claims, claimId)
    if c["status"] != "UNDER_REVIEW":
        raise invalid_state_transition("Claim must be UNDER_REVIEW to settle")
    data = body()
    amount_cents = req_int(data, "amount_cents")
    if amount_cents < 0:
        raise invalid_request("amount_cents must be non-negative")
    # Risk-allocation safety check (priority 5) before OCC
    if c["indemnified_by"] == "MANAGER":
        agmt = calc.find_active_agreement(c["property_id"])
        if agmt is not None:
            eff = parse_iso(agmt["effective_date"])
            end = parse_iso(agmt["term_end_date"])
            incident = parse_iso(c["incident_date"])
            if incident is None or eff is None or end is None or not (eff <= incident <= end):
                raise incident_outside_term()
        else:
            raise incident_outside_term()
    expected = data.get("expected_claim_version")
    if expected is None or expected != c["version"]:
        raise stale_version()

    manager_share, owner_share = calc.claim_settlement_shares(c, amount_cents)
    now = now_iso()
    settlement = {
        "id": new_id(),
        "claim_id": c["id"],
        "amount_cents": amount_cents,
        "manager_share_cents": manager_share,
        "owner_share_cents": owner_share,
        "created_at": now,
    }
    db.claim_settlements[settlement["id"]] = settlement
    prop = db.properties[c["property_id"]]
    # Release reserve, deduct owner share from property cash
    prop["cash_available_cents"] = (
        prop.get("cash_available_cents", 0) + c["reserved_amount_cents"] - owner_share
    )
    prop["updated_at"] = now
    prop["version"] += 1
    c["status"] = "SETTLED"
    c["updated_at"] = now
    c["version"] += 1
    return ok_object(claim_out(c))


@bp.post("/mgmt/claims/<claimId>/close")
def close_claim(claimId):
    require_roles("RiskOfficer")
    c = get_or_404(db.claims, claimId)
    if c["status"] == "SETTLED":
        pass
    elif c["status"] == "OPEN":
        if c["reserved_amount_cents"] > 0:
            raise reserve_outstanding()
    else:
        raise invalid_state_transition("Claim cannot be closed from its current state")
    c["status"] = "CLOSED"
    c["updated_at"] = now_iso()
    c["version"] += 1
    return ok_object(claim_out(c))


@bp.get("/mgmt/claims/<claimId>/settlements")
def list_settlements_for_claim(claimId):
    require_roles(*GET_ROLES)
    get_or_404(db.claims, claimId)
    items = sorted(
        (s for s in db.claim_settlements.values() if s["claim_id"] == claimId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    return paginate([settlement_out(s) for s in items])


@bp.get("/mgmt/claim-settlements/<claimSettlementId>")
def get_settlement(claimSettlementId):
    require_roles(*GET_ROLES)
    s = get_or_404(db.claim_settlements, claimSettlementId)
    return ok_object(settlement_out(s))


@bp.get("/mgmt/claim-settlements")
def list_settlements():
    require_roles(*GET_ROLES)
    claim_id = _arg("claim_id")
    items = sorted(db.claim_settlements.values(), key=lambda x: (x["created_at"], x["id"]))
    if claim_id is not None:
        items = [s for s in items if s["claim_id"] == claim_id]
    return paginate([settlement_out(s) for s in items])

"""Routes: benefits claims and appeals."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from constants import CLAIM_TYPES, RATING_STEPS, APPEAL_WINDOW_DAYS
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object, ok_list
from validation import (
    get_body, req_str, opt_str, req_enum, opt_int, opt_bool, pagination_params,
)

bp = Blueprint("claims", __name__)


@bp.post("/veteran-services/claims")
def create_claim():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    claimed_rating_pct = opt_int(body, "claimed_rating_pct", choices=RATING_STEPS)
    if claim_type == "DISABILITY_COMPENSATION" and claimed_rating_pct is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "claimed_rating_pct is required for DISABILITY_COMPENSATION", 400)
    if claim_type == "HEALTHCARE_ACCESS" and claimed_rating_pct is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "claimed_rating_pct must be null for HEALTHCARE_ACCESS", 400)
    dependent_count = opt_int(body, "dependent_count", default=0, minimum=0)
    coordination_consent = opt_bool(body, "coordination_consent", False)
    require_role(role, ["AccreditedRepresentative"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    # Priority 7: member must be VERIFIED
    if member["verification_status"] != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED", "member is not VERIFIED", 409)
    # Priority 10: duplication avoidance on the BENEFITS category
    if not coordination_consent and services.has_active_external_record(member_id, "BENEFITS"):
        raise ApiError("ERR_EXTERNAL_SERVICE_CONFLICT",
                       "an ACTIVE BENEFITS external service record exists", 409)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "claim_type": claim_type,
        "claimed_rating_pct": claimed_rating_pct,
        "dependent_count": dependent_count,
        "coordination_consent": coordination_consent,
        "provisional_monthly_cents": services.provisional_monthly_cents(
            claim_type, claimed_rating_pct),
        "decided_rating_pct": None, "final_monthly_cents": None, "outcome": None,
        "decided_by_officer_id": None, "decided_at": None, "status": "FILED",
    }
    services.stamp_new(rec)
    db.STORE["claims"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/members/<member_id>/claims")
def list_member_claims(member_id):
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["AccreditedRepresentative", "BenefitsOfficer", "IntakeCoordinator"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    status = request.args.get("status")
    items = [c for c in db.STORE["claims"].values()
             if c["member_id"] == member_id and (status is None or c["status"] == status)]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(c) for c in page], limit, offset, total)


@bp.get("/veteran-services/claims/<claim_id>")
def get_claim(claim_id):
    uid, role = authenticate()
    require_role(role, ["AccreditedRepresentative", "BenefitsOfficer"])
    claim = db.STORE["claims"].get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "claim does not exist", 404)
    return ok_object(services.serialize(claim))


@bp.post("/veteran-services/claims/<claim_id>/decide")
def decide_claim(claim_id):
    uid, role = authenticate()
    body = get_body()
    outcome = req_enum(body, "outcome", ("GRANTED", "DENIED"))
    decided_rating_pct = opt_int(body, "decided_rating_pct", choices=RATING_STEPS)
    require_role(role, ["BenefitsOfficer"])
    claim = db.STORE["claims"].get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "claim does not exist", 404)
    # Entity-dependent well-formedness of the rating field
    if outcome == "GRANTED" and decided_rating_pct is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "decided_rating_pct is required for a granted claim", 400)
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "claim is not FILED", 409)
    claim["outcome"] = outcome
    if outcome == "DENIED":
        claim["decided_rating_pct"] = 0
        claim["final_monthly_cents"] = 0
    else:
        claim["decided_rating_pct"] = decided_rating_pct
        claim["final_monthly_cents"] = services.final_monthly_cents(
            outcome, decided_rating_pct, claim["dependent_count"])
    claim["decided_by_officer_id"] = uid
    claim["decided_at"] = db.now()
    claim["status"] = "DECIDED"
    services.bump(claim)
    services.recompute_member_compensation(claim["member_id"])
    services.bump(db.STORE["members"][claim["member_id"]])
    return ok_object(services.serialize(claim))


@bp.post("/veteran-services/appeals")
def create_appeal():
    uid, role = authenticate()
    body = get_body()
    claim_id = req_str(body, "claim_id")
    grounds = opt_str(body, "grounds")
    require_role(role, ["AccreditedRepresentative"])
    claim = db.STORE["claims"].get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "claim does not exist", 404)
    # Priority 7: claim must be DECIDED
    if claim["status"] != "DECIDED":
        raise ApiError("ERR_CLAIM_NOT_APPEALABLE", "claim is not in DECIDED", 409)
    # Priority 11: appeal window (inclusive upper bound decided_at + 90 days)
    if db.now() > claim["decided_at"] + timedelta(days=APPEAL_WINDOW_DAYS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "the appeal window has closed", 422)
    # Priority 12: only DISABILITY_COMPENSATION claims are appealable
    if claim["claim_type"] != "DISABILITY_COMPENSATION":
        raise ApiError("ERR_CLAIM_TYPE_NOT_APPEALABLE",
                       "only DISABILITY_COMPENSATION claims are appealable", 409)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "claim_id": claim_id, "grounds": grounds, "status": "OPEN",
        "outcome": None, "new_rating_pct": None,
        "filed_at": db.now(), "decided_by_officer_id": None, "decided_at": None,
    }
    services.stamp_new(rec)
    db.STORE["appeals"][rec["id"]] = rec
    claim["status"] = "APPEAL_PENDING"
    services.bump(claim)
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/claims/<claim_id>/appeals")
def list_claim_appeals(claim_id):
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["AccreditedRepresentative", "BenefitsOfficer"])
    claim = db.STORE["claims"].get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "claim does not exist", 404)
    items = [a for a in db.STORE["appeals"].values() if a["claim_id"] == claim_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(a) for a in page], limit, offset, total)


@bp.post("/veteran-services/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    uid, role = authenticate()
    body = get_body()
    outcome = req_enum(body, "outcome", ("UPHELD", "OVERTURNED"))
    new_rating_pct = opt_int(body, "new_rating_pct", choices=RATING_STEPS)
    if outcome == "OVERTURNED" and new_rating_pct is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "new_rating_pct is required when outcome is OVERTURNED", 400)
    if outcome == "UPHELD" and new_rating_pct is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "new_rating_pct must be null when outcome is UPHELD", 400)
    require_role(role, ["BenefitsOfficer"])
    appeal = db.STORE["appeals"].get(appeal_id)
    if appeal is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND", "appeal does not exist", 404)
    if appeal["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "appeal is not OPEN", 409)
    claim = db.STORE["claims"].get(appeal["claim_id"])
    # Priority 8: segregation of duties
    if uid == claim["decided_by_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the appeal officer issued the claim's standing decision", 403)
    appeal["outcome"] = outcome
    appeal["new_rating_pct"] = new_rating_pct if outcome == "OVERTURNED" else None
    appeal["decided_by_officer_id"] = uid
    appeal["decided_at"] = db.now()
    appeal["status"] = "DECIDED"
    services.bump(appeal)
    if outcome == "OVERTURNED":
        # The standing decision is replaced: the claim is granted at the new rating
        claim["outcome"] = "GRANTED"
        claim["decided_rating_pct"] = new_rating_pct
        claim["final_monthly_cents"] = services.final_monthly_cents(
            "GRANTED", new_rating_pct, claim["dependent_count"])
        claim["decided_by_officer_id"] = uid
    claim["status"] = "DECIDED"
    claim["decided_at"] = appeal["decided_at"]  # appeal window re-anchors
    services.bump(claim)
    services.recompute_member_compensation(claim["member_id"])
    services.bump(db.STORE["members"][claim["member_id"]])
    return ok_object(services.serialize(appeal))

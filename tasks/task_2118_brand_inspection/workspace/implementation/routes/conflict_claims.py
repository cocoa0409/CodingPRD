"""Contesting a recorded brand."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert, touch
from errors import ApiError
from middleware import endpoint, require_owner
from response import object_response, paginate
from routes import lookup
from services import cascades
from validation import CLAIM_DECISIONS, CONFLICT_GROUNDS, body, opt_id, opt_str, req_enum, req_id

bp = Blueprint("conflict_claims", __name__)


@bp.post("/brand-conflict-claims")
@endpoint("LivestockOwner")
def file_claim():
    payload = body()
    claimant_owner_id = req_id(payload, "claimant_owner_id")
    respondent_registration_id = req_id(payload, "respondent_registration_id")
    grounds = req_enum(payload, "grounds", CONFLICT_GROUNDS)
    contested_application_id = opt_id(payload, "contested_application_id")

    lookup.owner(claimant_owner_id)
    lookup.registration(respondent_registration_id)
    if contested_application_id is not None:
        lookup.application(contested_application_id)

    require_owner(claimant_owner_id)

    row = base_row()
    row.update(
        {
            "claimant_owner_id": claimant_owner_id,
            "respondent_registration_id": respondent_registration_id,
            "contested_application_id": contested_application_id,
            "grounds": grounds,
            "status": "FILED",
            "decision_note": None,
        }
    )
    insert(db.claims, row)
    return object_response(row, 201)


@bp.get("/brand-conflict-claims/<claim_id>")
@endpoint("LivestockOwner", "BrandRecorder", "BoardAdmin")
def read_claim(claim_id):
    return object_response(lookup.claim(claim_id))


@bp.get("/brand-conflict-claims")
@endpoint("LivestockOwner", "BrandRecorder", "BoardAdmin")
def list_claims():
    rows = lookup.filtered(
        db.claims,
        {
            "claimant_owner_id": request.args.get("claimant_owner_id"),
            "respondent_registration_id": request.args.get("respondent_registration_id"),
            "contested_application_id": request.args.get("contested_application_id"),
            "status": request.args.get("status"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/brand-conflict-claims/<claim_id>/adjudicate")
@endpoint("BrandRecorder")
def adjudicate_claim(claim_id):
    claim = lookup.claim(claim_id)
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", "The contest is not awaiting adjudication.")
    claim["status"] = "UNDER_ADJUDICATION"
    touch(claim)
    return object_response(claim)


@bp.post("/brand-conflict-claims/<claim_id>/decide")
@endpoint("BrandRecorder")
def decide_claim(claim_id):
    payload = body()
    decision = req_enum(payload, "decision", CLAIM_DECISIONS)
    decision_note = opt_str(payload, "decision_note")

    claim = lookup.claim(claim_id)
    if claim["status"] != "UNDER_ADJUDICATION":
        raise ApiError("ERR_CLAIM_INVALID_STATE", "The contest is not under adjudication.")

    registration = db.registrations.get(claim["respondent_registration_id"])
    if decision == "SUSTAIN":
        if registration is None or registration["status"] not in ("ACTIVE", "GRACE", "ENCUMBERED"):
            raise ApiError(
                "ERR_REGISTRATION_INVALID_STATE", "The respondent record may no longer be revoked."
            )
        claim["status"] = "SUSTAINED"
        claim["decision_note"] = decision_note
        touch(claim)
        cascades.revoke_registration_and_cascade(registration, unschedule=True)
    else:
        claim["status"] = "DISMISSED"
        claim["decision_note"] = decision_note
        touch(claim)

    return object_response(claim)

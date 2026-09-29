"""Challenges, court review, and fraud referrals with their adjudication."""

from flask import Blueprint

import response
import validation as v
from db import (db, get_batch, get_challenge, get_circulator, get_petition,
                get_referral, new_resource, now, serialize, touch)
from errors import ApiError
from middleware import require_auth, require_challenge_owner
from services import calculations as calc
from services import cascades

CHALLENGE_READ_ROLES = ("SosAdmin", "ElectionsExaminer", "Proponent", "Challenger")
REFERRAL_READ_ROLES = ("SosAdmin", "ElectionsExaminer", "CountyClerk", "Challenger")

bp = Blueprint("challenges", __name__)


# ---------------------------------------------------------------------------
# challenges
# ---------------------------------------------------------------------------
@bp.route("/challenges/<challenge_id>", methods=["GET"])
def read_challenge(challenge_id):
    require_auth(CHALLENGE_READ_ROLES)
    return response.single(serialize(get_challenge(challenge_id)))


@bp.route("/challenges", methods=["GET"])
def list_challenges():
    require_auth(CHALLENGE_READ_ROLES)
    return response.listing(list(db.challenges.values()), {
        "petition_id": ("str", "petition_id"),
        "status": ("str", "status"),
        "grounds": ("str", "grounds"),
    })


@bp.route("/challenges/<challenge_id>/escalate", methods=["POST"])
def escalate_challenge(challenge_id):
    user_id, role = require_auth(["Challenger"])
    body = v.body()
    docket = v.as_string(v.required(body, "court_docket_number"), "court_docket_number")
    challenge = get_challenge(challenge_id)
    require_challenge_owner(challenge, user_id, role)
    if challenge["status"] != "FILED":
        raise ApiError("ERR_INVALID_CHALLENGE_STATE")
    if now() >= challenge["_review_deadline_at_dt"]:
        raise ApiError("ERR_CHALLENGE_REVIEW_WINDOW_EXPIRED")
    challenge["court_docket_number"] = docket
    challenge["status"] = "COURT_REVIEW"
    touch(challenge)
    petition = db.petitions.get(challenge["petition_id"])
    if petition is not None:
        petition["challenge_status"] = "COURT_REVIEW"
        touch(petition)
    return response.single(serialize(challenge))


@bp.route("/challenges/<challenge_id>/rule", methods=["POST"])
def rule_challenge(challenge_id):
    require_auth(["SosAdmin"])
    body = v.body()
    ruling = v.as_enum(v.required(body, "ruling"), "ruling", ("AFFIRM", "REVERSE"))
    challenge = get_challenge(challenge_id)
    if challenge["status"] != "COURT_REVIEW":
        raise ApiError("ERR_INVALID_CHALLENGE_STATE")
    challenge["ruling"] = ruling
    petition = db.petitions.get(challenge["petition_id"])
    if ruling == "AFFIRM":
        challenge["status"] = "DISMISSED"
        if petition is not None:
            petition["challenge_status"] = "COURT_AFFIRMED"
            touch(petition)
    else:
        challenge["status"] = "UPHELD"
        if petition is not None:
            petition["challenge_status"] = "COURT_REVERSED"
            if petition["status"] == "PENDING_CERTIFICATION":
                petition["status"] = "PENDING_FAILURE"
            elif petition["status"] == "PENDING_FAILURE":
                petition["status"] = "PENDING_CERTIFICATION"
            touch(petition)
    touch(challenge)
    return response.single(serialize(challenge))


@bp.route("/challenges/<challenge_id>/dismiss", methods=["POST"])
def dismiss_challenge(challenge_id):
    require_auth(["SosAdmin"])
    body = v.body()
    if "reason" in body and body["reason"] is not None:
        v.as_string(body["reason"], "reason")
    challenge = get_challenge(challenge_id)
    if challenge["status"] != "FILED":
        raise ApiError("ERR_INVALID_CHALLENGE_STATE")
    challenge["status"] = "DISMISSED"
    touch(challenge)
    petition = db.petitions.get(challenge["petition_id"])
    if petition is not None:
        petition["challenge_status"] = "NONE"
        touch(petition)
    return response.single(serialize(challenge))


# ---------------------------------------------------------------------------
# fraud referrals
# ---------------------------------------------------------------------------
@bp.route("/fraud-referrals", methods=["POST"])
def open_referral():
    user_id, role = require_auth(["ElectionsExaminer", "SosAdmin", "CountyClerk"])
    body = v.body()
    petition_id = v.as_id(v.required(body, "petition_id"), "petition_id")
    circulator_id = v.as_id(v.required(body, "circulator_id"), "circulator_id")
    referral_type = v.as_enum(v.required(body, "referral_type"), "referral_type",
                              ("FORGED_SIGNATURES", "CIRCULATOR_MISCONDUCT",
                               "FALSE_AFFIDAVIT"))
    narrative = v.as_string(v.required(body, "narrative"), "narrative")
    batch_id = v.optional(body, "batch_id")
    if batch_id is not None:
        batch_id = v.as_id(batch_id, "batch_id")

    petition = get_petition(petition_id)
    circulator = get_circulator(circulator_id)
    batch = get_batch(batch_id) if batch_id is not None else None
    if batch is not None and role == "CountyClerk" and batch["county_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    referral = new_resource({
        "petition_id": petition["id"],
        "circulator_id": circulator["id"],
        "batch_id": batch["id"] if batch is not None else None,
        "referral_type": referral_type,
        "narrative": narrative,
        "opened_by_examiner_id": user_id,
        "adjudicated_by_examiner_id": None,
        "referred_to_ag": False,
        "finding": None,
        "voided_signature_count": 0,
        "status": "OPENED",
    })
    db.fraud_referrals[referral["id"]] = referral
    calc.recompute_credibility(circulator)
    touch(circulator)
    return response.single(serialize(referral), 201)


@bp.route("/fraud-referrals/<referral_id>", methods=["GET"])
def read_referral(referral_id):
    require_auth(REFERRAL_READ_ROLES)
    return response.single(serialize(get_referral(referral_id)))


@bp.route("/fraud-referrals", methods=["GET"])
def list_referrals():
    require_auth(REFERRAL_READ_ROLES)
    return response.listing(list(db.fraud_referrals.values()), {
        "petition_id": ("str", "petition_id"),
        "circulator_id": ("str", "circulator_id"),
        "batch_id": ("str", "batch_id"),
        "referral_type": ("str", "referral_type"),
        "status": ("str", "status"),
    })


@bp.route("/fraud-referrals/<referral_id>/refer-to-ag", methods=["POST"])
def refer_to_ag(referral_id):
    require_auth(["ElectionsExaminer", "SosAdmin"])
    v.body()
    referral = get_referral(referral_id)
    if referral["status"] != "OPENED":
        raise ApiError("ERR_REFERRAL_NOT_WITH_AG")
    referral["status"] = "REFERRED_TO_AG"
    referral["referred_to_ag"] = True
    touch(referral)
    return response.single(serialize(referral))


@bp.route("/fraud-referrals/<referral_id>/adjudicate", methods=["POST"])
def adjudicate_referral(referral_id):
    user_id, role = require_auth(["ElectionsExaminer", "SosAdmin"])
    body = v.body()
    finding = v.as_enum(v.required(body, "finding"), "finding",
                        ("SUBSTANTIATED", "UNSUBSTANTIATED"))
    referral = get_referral(referral_id)
    if referral["opened_by_examiner_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if referral["status"] != "REFERRED_TO_AG":
        raise ApiError("ERR_REFERRAL_NOT_WITH_AG")
    circulator = db.circulators.get(referral["circulator_id"])
    referral["finding"] = finding
    referral["adjudicated_by_examiner_id"] = user_id
    referral["status"] = finding
    touch(referral)
    if circulator is not None:
        if finding == "SUBSTANTIATED":
            cascades.fraud_substantiated_cascade(referral, circulator)
        else:
            calc.recompute_credibility(circulator)
            touch(circulator)
    return response.single(serialize(referral))

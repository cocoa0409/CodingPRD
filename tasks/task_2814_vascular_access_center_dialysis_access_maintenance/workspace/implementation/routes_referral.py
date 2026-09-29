"""Referral intake, the revision loop and triage.  PRD section 3.3."""
from flask import Blueprint, request

import calc
from core import (
    ApiError, authenticate, base_record, db, envelope_object, facility_scope,
    filter_equals, get_body, list_response, must_get, now_str, opt_int, opt_str,
    public, req_enum, req_id, req_int, req_str, touch,
)

bp = Blueprint("referral", __name__)

SUSPECTED_PROBLEMS = ("STENOSIS", "THROMBOSIS", "CATHETER_DYSFUNCTION", "MATURATION_FAILURE")
MECHANICAL_PROBLEMS = ("STENOSIS", "THROMBOSIS", "CATHETER_DYSFUNCTION")


@bp.post("/referrals")
def create_referral():
    user_id, role = authenticate(("FacilityCoordinator", "AccessCoordinator", "CenterAdmin"))
    body = get_body()
    access_id = req_id(body, "access_id")
    facility_id = req_id(body, "referring_facility_id")
    suspected_problem = req_enum(body, "suspected_problem", SUSPECTED_PROBLEMS)
    clinical_narrative = req_str(body, "clinical_narrative")
    missed = opt_int(body, "missed_treatment_count", 0, minimum=0, maximum=60)

    must_get(db.accesses, access_id, "ERR_ACCESS_NOT_FOUND")
    facility = must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    facility_scope(role, user_id, facility_id)

    referral = base_record()
    referral.update({
        "access_id": access_id,
        "referring_facility_id": facility_id,
        "suspected_problem": suspected_problem,
        "clinical_narrative": clinical_narrative,
        "missed_treatment_count": missed,
        "status": "SUBMITTED",
        "triage_score": None,
        "triage_variant": None,
        "urgency": None,
        "triaged_at": None,
        "completed_at": None,
        "info_request_count": 0,
        "hold_reason": None,
        "decline_reason": None,
    })
    db.referrals[referral["id"]] = referral

    # Submission immediately rescores the referring facility (PRD 3.3, 3.4).
    calc.score_facility(facility)
    return envelope_object(public(referral)), 201


@bp.post("/referrals/<referral_id>/request-info")
def request_info(referral_id):
    authenticate(("AccessCoordinator", "CenterAdmin"))
    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    opt_str(body, "info_request_note")
    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERRAL_STATE_INVALID")

    referral["status"] = "INFO_REQUESTED"
    referral["hold_reason"] = "COORDINATOR_REQUEST"
    referral["info_request_count"] += 1
    touch(referral)
    return envelope_object(public(referral)), 200


@bp.post("/referrals/<referral_id>/resubmit")
def resubmit(referral_id):
    user_id, role = authenticate(("FacilityCoordinator",))
    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    clinical_narrative = req_str(body, "clinical_narrative")
    missed = None
    if body.get("missed_treatment_count") is not None:
        missed = req_int(body, "missed_treatment_count", minimum=0, maximum=60)

    facility_scope(role, user_id, referral["referring_facility_id"])
    if referral["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_REFERRAL_STATE_INVALID")

    referral["status"] = "SUBMITTED"
    referral["clinical_narrative"] = clinical_narrative
    if missed is not None:
        referral["missed_treatment_count"] = missed
    referral["hold_reason"] = None
    referral["triage_score"] = None
    referral["triage_variant"] = None
    referral["urgency"] = None
    referral["triaged_at"] = None
    touch(referral)
    return envelope_object(public(referral)), 200


@bp.post("/referrals/<referral_id>/triage")
def triage(referral_id):
    authenticate(("AccessCoordinator", "CenterAdmin"))
    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERRAL_STATE_INVALID")

    facility = db.facilities[referral["referring_facility_id"]]
    if facility["contract_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_FACILITY_SUSPENDED")

    access = db.accesses[referral["access_id"]]
    if not calc.readings_at_or_before_clock(access["id"]):
        raise ApiError("ERR_INSUFFICIENT_SURVEILLANCE")
    window = calc.triage_window_readings(access["id"])
    if not window:
        raise ApiError("ERR_INSUFFICIENT_SURVEILLANCE")
    if access["status"] == "ABANDONED":
        raise ApiError("ERR_ACCESS_ABANDONED")

    score, variant, urgency = calc.compute_triage(window, referral["missed_treatment_count"])
    referral["status"] = "TRIAGED"
    referral["triage_score"] = score
    referral["triage_variant"] = variant
    referral["urgency"] = urgency
    referral["triaged_at"] = now_str()
    touch(referral)

    if referral["suspected_problem"] in MECHANICAL_PROBLEMS and access["status"] == "IN_USE":
        access["status"] = "DYSFUNCTIONAL"
        touch(access)

    calc.score_facility(facility)
    return envelope_object(public(referral)), 200


@bp.post("/referrals/<referral_id>/decline")
def decline(referral_id):
    authenticate(("AccessCoordinator", "CenterAdmin"))
    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    decline_reason = req_str(body, "decline_reason")
    if referral["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        raise ApiError("ERR_REFERRAL_STATE_INVALID")

    referral["status"] = "DECLINED"
    referral["decline_reason"] = decline_reason
    touch(referral)

    calc.score_facility(db.facilities[referral["referring_facility_id"]])
    return envelope_object(public(referral)), 200


@bp.post("/referrals/<referral_id>/missed-treatments")
def update_missed_treatments(referral_id):
    user_id, role = authenticate(("FacilityCoordinator", "AccessCoordinator", "CenterAdmin"))
    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    missed = req_int(body, "missed_treatment_count", minimum=0, maximum=60)
    facility_scope(role, user_id, referral["referring_facility_id"])

    referral["missed_treatment_count"] = missed
    touch(referral)

    calc.score_facility(db.facilities[referral["referring_facility_id"]])
    return envelope_object(public(referral)), 200


@bp.get("/referrals/<referral_id>")
def get_referral(referral_id):
    user_id, role = authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator",
                                  "Interventionalist", "Coder"))
    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    facility_scope(role, user_id, referral["referring_facility_id"])
    return envelope_object(public(referral)), 200


@bp.get("/referrals")
def list_referrals():
    authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator", "Interventionalist"))
    rows = list(db.referrals.values())
    rows = filter_equals(rows, "access_id", request.args.get("access_id"))
    rows = filter_equals(rows, "referring_facility_id", request.args.get("referring_facility_id"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    rows = filter_equals(rows, "urgency", request.args.get("urgency"))
    return list_response(calc.seq_sorted(rows))

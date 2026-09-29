"""Evaluation and family assessment scheduling and completion."""
from flask import Blueprint, g, request

import domain as D
from auth import STAFF_READ, endpoint
from envelope import paginate, single
from errors import fail
from helpers import (get_assessment, get_referral, not_future, ordered_dates,
                     ser_assessment)
from services import cascades, compute
from store import db, flush, new_row, ordered, set_field, set_fields
from validate import (Field, parse_body, v_date, v_enum, v_id, v_int, v_list,
                      v_str)

bp = Blueprint("assessments", __name__)


@bp.route("/ei/assessments", methods=["POST"])
@endpoint(["Evaluator"])
def create_assessment():
    payload = parse_body([
        Field("referral_id", v_id()),
        Field("assessment_type", v_enum(D.ASSESSMENT_TYPES)),
        Field("scheduled_date", v_date()),
        Field("setting_code", v_enum(D.SETTING_CODES)),
        Field("natural_environment_justification", v_str(20), required=False),
        Field("domains_assessed", v_list(v_enum(D.DOMAINS), min_items=1),
              required=False),
    ])
    if (payload["setting_code"] in D.NON_NATURAL_SETTINGS
            and not payload["natural_environment_justification"]):
        fail("ERR_INVALID_REQUEST",
             "Field 'natural_environment_justification' is required for a "
             "CLINIC or PROGRAM_OFFICE setting.")
    referral = get_referral(payload["referral_id"])
    if referral["status"] in D.REFERRAL_TERMINAL:
        fail("ERR_REFERRAL_STATE_INVALID",
             "A terminal case accepts no further evaluation work.")
    if payload["assessment_type"] == "INITIAL_EVALUATION":
        supplied = set(payload["domains_assessed"] or [])
        if supplied != set(D.DOMAINS):
            fail("ERR_EVALUATION_DOMAINS_INCOMPLETE",
                 "An initial evaluation must cover all five developmental domains.")
    assessment = new_row({
        "referral_id": referral["id"],
        "assessment_type": payload["assessment_type"],
        "scheduled_date": payload["scheduled_date"],
        "setting_code": payload["setting_code"],
        "natural_environment_justification":
            payload["natural_environment_justification"],
        "domains_assessed": payload["domains_assessed"],
        "evaluator_user_id": g.user_id,
        "status": "SCHEDULED",
        "completion_date": None,
        "family_unavailable_days": 0,
        "eligibility_recommendation": None,
    })
    db.assessments[assessment["id"]] = assessment
    if (payload["assessment_type"] == "SUPPLEMENTAL_EVALUATION"
            and referral["status"] == "IFSP_PENDING"):
        live = [p for p in compute.referral_ifsps(referral["id"])
                if p["status"] in ("ACTIVE", "AMENDMENT_PENDING")]
        if not live:
            set_field(referral, "status", "EVALUATION_PENDING", bump=False)
            cascades.withdraw_draft_plans(referral)
            compute.recompute_initial_meeting_date(referral)
            compute.recompute_timeline(referral)
            compute.recompute_case_weight(referral)
            compute.recompute_monthly_contact(referral)
            compute.recompute_coordinator(
                db.coordinators.get(referral["coordinator_id"]))
    flush()
    return single(ser_assessment(assessment), 201)


@bp.route("/ei/assessments/<assessment_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_assessment(assessment_id):
    return single(ser_assessment(get_assessment(assessment_id)))


@bp.route("/ei/assessments", methods=["GET"])
@endpoint(STAFF_READ)
def list_assessments():
    rows = ordered(db.assessments)
    referral_id = request.args.get("referral_id")
    assessment_type = request.args.get("assessment_type")
    status = request.args.get("status")
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if assessment_type is not None:
        rows = [r for r in rows if r["assessment_type"] == assessment_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_assessment)


@bp.route("/ei/assessments/<assessment_id>/complete", methods=["POST"])
@endpoint(["Evaluator"])
def complete_assessment(assessment_id):
    payload = parse_body([
        Field("completion_date", v_date()),
        Field("eligibility_recommendation", v_enum(D.ELIGIBILITY_RECOMMENDATIONS)),
        Field("family_unavailable_days", v_int(0, 120), required=False, default=0),
    ])
    assessment = get_assessment(assessment_id)
    if assessment["status"] != "SCHEDULED":
        fail("ERR_ASSESSMENT_NOT_SCHEDULED",
             "Only a SCHEDULED assessment may be completed.")
    referral = db.referrals.get(assessment["referral_id"])
    not_future(payload["completion_date"], "completion_date")
    if referral is not None:
        ordered_dates(referral["referral_received_date"],
                      payload["completion_date"],
                      "completion_date must be on or after "
                      "referral_received_date.")
    set_fields(assessment, {
        "status": "COMPLETED",
        "completion_date": payload["completion_date"],
        "family_unavailable_days": payload["family_unavailable_days"],
        "eligibility_recommendation": payload["eligibility_recommendation"],
    })
    if referral is not None:
        compute.recompute_timeline(referral)
    flush()
    return single(ser_assessment(assessment))

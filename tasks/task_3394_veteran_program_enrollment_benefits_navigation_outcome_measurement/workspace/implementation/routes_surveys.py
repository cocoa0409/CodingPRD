"""Routes: outcome survey submission and donor reports."""
from decimal import Decimal

from flask import Blueprint

import db
import services
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object
from validation import get_body, req_enum, req_int, req_dt

bp = Blueprint("surveys", __name__)


@bp.post("/veteran-services/surveys/<survey_id>/submit")
def submit_survey(survey_id):
    uid, role = authenticate()
    body = get_body()
    q1 = req_int(body, "q1", minimum=1, maximum=5)
    q2 = req_int(body, "q2", minimum=1, maximum=5)
    q3 = req_int(body, "q3", minimum=1, maximum=5)
    q4 = req_int(body, "q4", minimum=1, maximum=5)
    q5 = req_int(body, "q5", minimum=1, maximum=5)
    require_role(role, ["ProgramMember", "IntakeCoordinator"])
    survey = db.STORE["surveys"].get(survey_id)
    if survey is None:
        raise ApiError("ERR_SURVEY_NOT_FOUND", "survey does not exist", 404)
    # Priority 5: a ProgramMember submits only their own enrollment's surveys
    if role == "ProgramMember":
        enrollment = db.STORE["enrollments"].get(survey["enrollment_id"])
        if enrollment is None or enrollment["member_id"] != uid:
            raise ApiError("ERR_RESOURCE_NOT_OWNED",
                           "the survey does not belong to the caller", 403)
    # Priority 7: submission is allowed only while the survey is OPEN
    if survey["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "survey is not OPEN", 409)
    survey["q1"] = q1
    survey["q2"] = q2
    survey["q3"] = q3
    survey["q4"] = q4
    survey["q5"] = q5
    survey["wellbeing_score"] = (q1 + q2 + q3 + q4 + q5) * 4
    survey["submitted_at"] = db.now()
    survey["status"] = "SUBMITTED"
    services.bump(survey)
    return ok_object(services.serialize(survey))


@bp.post("/veteran-services/donor-reports")
def create_donor_report():
    uid, role = authenticate()
    body = get_body()
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_end < period_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "period_end must be at or after period_start", 400)
    methodology = req_enum(body, "methodology", ("ITT", "COMPLETER"))
    track_weights = None
    if "track_weights" in body and body["track_weights"] is not None:
        tw = body["track_weights"]
        if not isinstance(tw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "track_weights must be an object", 400)
        total = Decimal(0)
        for key, value in tw.items():
            if (not isinstance(key, str) or isinstance(value, bool)
                    or not isinstance(value, (int, float))):
                raise ApiError("ERR_INVALID_REQUEST",
                               "track_weights values must be numbers", 400)
            total += Decimal(str(value))
        if total != Decimal(1):
            raise ApiError("ERR_INVALID_REQUEST",
                           "track_weights values must sum to exactly 1.0", 400)
        track_weights = tw
    require_role(role, ["OutcomeAnalyst"])
    per_track, cohort_total, overall = services.build_donor_report(
        period_start, period_end, methodology, track_weights)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "period_start": period_start, "period_end": period_end,
        "methodology": methodology, "track_weights": track_weights,
        "cohort_size_total": cohort_total,
        "per_track": per_track,
        "overall_effect": overall,
    }
    services.stamp_new(rec, lean=True)  # DonorReport: id + created_at only
    db.STORE["donor_reports"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/donor-reports/<report_id>")
def get_donor_report(report_id):
    uid, role = authenticate()
    require_role(role, ["OutcomeAnalyst"])
    rec = db.STORE["donor_reports"].get(report_id)
    if rec is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", "donor report does not exist", 404)
    return ok_object(services.serialize(rec))

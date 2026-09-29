"""Medical forms: filing, review and in-place resubmission."""
from flask import Blueprint

import db
import derive
from core import (MEDICAL_FORM_MAX_REVISIONS, MEDICAL_FORM_STATUSES,
                  MEDICAL_FORM_VALIDITY_DAYS, MEDICAL_RESTRICTIONS,
                  REGISTRATION_VALIDITY_DAYS, REJECTION_REASON_CODES,
                  REVIEW_DECISIONS, add_days, auth, bad_request, clock_date,
                  clock_str, fail, fmt_date, get_body, ok, opt_bool, paginate,
                  parse_date, query_enum, req_date_field, req_enum,
                  req_list_of_enum, req_str)
from serialize import ser_athlete, ser_medical_form

bp = Blueprint("medical", __name__)


def _read_form_payload(body):
    exam_date = req_date_field(body, "exam_date")
    physician_name = req_str(body, "physician_name", 2, 120)
    physician_license_id = req_str(body, "physician_license_id", 4, 32)
    cardiac = body.get("attestation_cardiac_clearance")
    if cardiac is not None and not isinstance(cardiac, bool):
        bad_request("attestation_cardiac_clearance must be a boolean.")
    seizure = body.get("attestation_seizure_history")
    if seizure is not None and not isinstance(seizure, bool):
        bad_request("attestation_seizure_history must be a boolean.")
    atlantoaxial = opt_bool(body, "attestation_atlantoaxial_screen")
    restrictions = None
    if "restrictions" in body and body.get("restrictions") is not None:
        restrictions = req_list_of_enum(body, "restrictions",
                                        MEDICAL_RESTRICTIONS)
        if "NONE" in restrictions and len(restrictions) > 1:
            bad_request("restrictions may not combine NONE with any other "
                        "value.")
    return {
        "exam_date": fmt_date(exam_date),
        "physician_name": physician_name,
        "physician_license_id": physician_license_id,
        "attestation_cardiac_clearance": cardiac,
        "attestation_seizure_history": seizure,
        "attestation_atlantoaxial_screen": atlantoaxial,
        "restrictions": restrictions,
    }


def _safety_gates(athlete, payload, include_future=True):
    if payload["attestation_cardiac_clearance"] is not True or (
            payload["attestation_seizure_history"] is None):
        fail("ERR_MEDICAL_ATTESTATION_INCOMPLETE", 422,
             "Cardiac clearance must be affirmative and seizure history must "
             "be recorded.")
    if athlete["down_syndrome_flag"] and (
            payload["attestation_atlantoaxial_screen"] is not True):
        fail("ERR_ATLANTOAXIAL_SCREEN_MISSING", 422,
             "An affirmative atlantoaxial screening attestation is required "
             "for an athlete with Down syndrome.")
    exam_date = parse_date(payload["exam_date"])
    today = clock_date()
    if include_future and exam_date > today:
        fail("ERR_EXAM_DATE_IN_FUTURE", 422,
             "exam_date may not fall after the logical clock date.")
    if add_days(exam_date, MEDICAL_FORM_VALIDITY_DAYS) < today:
        fail("ERR_MEDICAL_EXAM_STALE", 422,
             "This exam is already past its three-year shelf life.")


def _restrictions_are_none(restrictions):
    if restrictions is None:
        return True
    return list(restrictions) == ["NONE"]


def _set_pending_review(athlete):
    if athlete["medical_status"] != "HOLD":
        db.apply_changes(athlete, {"medical_status": "PENDING_REVIEW"})


@bp.get("/athletes/<rid>/medical-forms")
def list_medical_forms(rid):
    auth(["ProgramManager", "MedicalReviewer", "HealthScreeningLead"],
         write=False)
    athlete = derive.require("athletes", rid)
    status = query_enum("status", MEDICAL_FORM_STATUSES)
    rows = [f for f in db.medical_forms.values()
            if f["athlete_id"] == athlete["id"]]
    if status:
        rows = [f for f in rows if f["status"] == status]
    return paginate(rows, ser_medical_form)


@bp.post("/athletes/<rid>/medical-forms")
def create_medical_form(rid):
    auth(["ProgramManager", "MedicalReviewer"])
    athlete = derive.require("athletes", rid)
    payload = _read_form_payload(get_body())
    if athlete["registration_status"] == "WITHDRAWN":
        fail("ERR_MEDICAL_FORM_STATE_INVALID", 409,
             "A withdrawn athlete may not have a medical form filed.")
    if any(f["athlete_id"] == athlete["id"] and f["status"] == "SUBMITTED"
           for f in db.medical_forms.values()):
        fail("ERR_MEDICAL_FORM_STATE_INVALID", 409,
             "This athlete already has a medical form awaiting review.")
    _safety_gates(athlete, payload)
    exam_date = parse_date(payload["exam_date"])
    fields = dict(payload)
    fields.update({
        "athlete_id": athlete["id"],
        "status": "SUBMITTED",
        "revision_count": 0,
        "reviewed_by_user_id": None,
        "rejection_reason_code": None,
        "expires_on": fmt_date(add_days(exam_date, MEDICAL_FORM_VALIDITY_DAYS)),
        "approved_at": None,
    })
    form = db.new_row("medical_forms", fields)
    _set_pending_review(athlete)
    return ok(ser_medical_form(form), 201)


@bp.post("/medical-forms/<rid>/review")
def review_medical_form(rid):
    _role, user_id = auth(["MedicalReviewer"])
    form = derive.require("medical_forms", rid)
    body = get_body()
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    rejection_reason_code = None
    if decision == "REJECT":
        rejection_reason_code = req_enum(body, "rejection_reason_code",
                                        REJECTION_REASON_CODES)
    athlete = db.athletes[form["athlete_id"]]
    if form["status"] != "SUBMITTED":
        fail("ERR_MEDICAL_FORM_STATE_INVALID", 409,
             "Only a SUBMITTED medical form may be reviewed.")
    if decision == "APPROVE":
        _safety_gates(athlete, form, include_future=False)
        for other in db.medical_forms.values():
            if (other["athlete_id"] == athlete["id"]
                    and other["id"] != form["id"]
                    and other["status"] == "APPROVED"):
                other["status"] = "SUPERSEDED"
                db.touch(other)
        form["status"] = "APPROVED"
        form["approved_at"] = clock_str()
        form["reviewed_by_user_id"] = user_id
        db.touch(form)
        exam_date = parse_date(form["exam_date"])
        form_expiry = add_days(exam_date, MEDICAL_FORM_VALIDITY_DAYS)
        year_out = add_days(clock_date(), REGISTRATION_VALIDITY_DAYS)
        changes = {
            "medical_status": ("CLEARED"
                               if _restrictions_are_none(form["restrictions"])
                               else "RESTRICTED"),
            "current_medical_form_id": form["id"],
            "registration_expires_on": fmt_date(min(form_expiry, year_out)),
        }
        if athlete["registration_status"] in ("PENDING_MEDICAL", "LAPSED"):
            changes["registration_status"] = "ACTIVE"
        db.apply_changes(athlete, changes)
    else:
        form["status"] = "REJECTED"
        form["rejection_reason_code"] = rejection_reason_code
        form["reviewed_by_user_id"] = user_id
        db.touch(form)
        if athlete["medical_status"] == "PENDING_REVIEW":
            db.apply_changes(athlete, {"medical_status": "NONE"})
    derive.recompute_teams_for_athlete(athlete)
    derive.recompute_program(derive.program_of_athlete(athlete))
    return ok(ser_medical_form(form))


@bp.post("/medical-forms/<rid>/resubmit")
def resubmit_medical_form(rid):
    auth(["ProgramManager", "MedicalReviewer"])
    form = derive.require("medical_forms", rid)
    payload = _read_form_payload(get_body())
    athlete = db.athletes[form["athlete_id"]]
    if form["status"] != "REJECTED":
        fail("ERR_MEDICAL_FORM_STATE_INVALID", 409,
             "Only a REJECTED medical form may be resubmitted.")
    if athlete["registration_status"] == "WITHDRAWN":
        fail("ERR_MEDICAL_FORM_STATE_INVALID", 409,
             "A withdrawn athlete's form may not be resubmitted.")
    if form["revision_count"] >= MEDICAL_FORM_MAX_REVISIONS:
        fail("ERR_RESUBMIT_LIMIT_REACHED", 409,
             "This form has already been revised three times.")
    _safety_gates(athlete, payload)
    exam_date = parse_date(payload["exam_date"])
    form.update(payload)
    form["status"] = "SUBMITTED"
    form["revision_count"] = form["revision_count"] + 1
    form["rejection_reason_code"] = None
    form["expires_on"] = fmt_date(add_days(exam_date,
                                           MEDICAL_FORM_VALIDITY_DAYS))
    db.touch(form)
    _set_pending_review(athlete)
    return ok(ser_medical_form(form))

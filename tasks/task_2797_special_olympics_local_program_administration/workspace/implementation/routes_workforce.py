"""Volunteers and the fork-join credentialing workflow."""
from flask import Blueprint

import db
import derive
from core import (ADULT_AGE_YEARS, CREDENTIAL_STATUSES, FLAGGED_REVIEW_DAYS,
                  ROLE_CLASSES, SCREENING_RESULTS, SCREENING_VALIDITY_DAYS,
                  TRAINING_VALIDITY_DAYS_BY_ROLE, VOLUNTEER_CLASSES, add_days,
                  auth, bad_request, clock_date, clock_str, fail, fmt_date,
                  get_body, ok, opt_str, paginate, parse_date, query_enum,
                  req_date_field, req_enum, req_str)
from serialize import ser_credential, ser_volunteer, volunteer_is_minor

bp = Blueprint("workforce", __name__)

RECORDABLE_FRESH_SCREENING = ("INITIATED", "TRAINING_COMPLETE")
RECORDABLE_FRESH_TRAINING = ("INITIATED", "SCREENING_CLEARED")
RENEWAL_STATES = ("EXPIRED", "RENEWAL_IN_PROGRESS")


def _step_conflict():
    fail("ERR_CREDENTIAL_STEP_ALREADY_RECORDED", 409,
         "This credential branch cannot be recorded in the credential's "
         "current state.")

# --------------------------------------------------------------- volunteers ---


@bp.post("/programs/<rid>/volunteers")
def create_volunteer(rid):
    auth(["ProgramManager", "CredentialingOfficer"])
    program = derive.require("programs", rid)
    body = get_body()
    full_name = req_str(body, "full_name", 2, 120)
    email = req_str(body, "email", 1, None)
    if "@" not in email:
        bad_request("email must contain an '@' character.")
    date_of_birth = req_date_field(body, "date_of_birth")
    volunteer_class = req_enum(body, "volunteer_class", VOLUNTEER_CLASSES)
    for other in derive.program_volunteers(program["id"]):
        if other["email"] == email:
            bad_request("email is already used by another volunteer of this "
                        "program.")
    volunteer = db.new_row("volunteers", {
        "program_id": program["id"],
        "full_name": full_name,
        "email": email,
        "date_of_birth": fmt_date(date_of_birth),
        "volunteer_class": volunteer_class,
    })
    return ok(ser_volunteer(volunteer), 201)


@bp.get("/volunteers/<rid>")
def get_volunteer(rid):
    auth(["ProgramManager", "CredentialingOfficer", "CompetitionDirector"],
         write=False)
    volunteer = derive.require("volunteers", rid)
    return ok(ser_volunteer(volunteer))


@bp.get("/volunteers/<rid>/credentials")
def list_volunteer_credentials(rid):
    auth(["ProgramManager", "CredentialingOfficer", "CompetitionDirector"],
         write=False)
    volunteer = derive.require("volunteers", rid)
    status = query_enum("status", CREDENTIAL_STATUSES)
    role_class = query_enum("role_class", ROLE_CLASSES)
    rows = [c for c in db.credentials.values()
            if c["volunteer_id"] == volunteer["id"]]
    if status:
        rows = [c for c in rows if c["status"] == status]
    if role_class:
        rows = [c for c in rows if c["role_class"] == role_class]
    return paginate(rows, ser_credential)


@bp.get("/credentials/<rid>")
def get_credential(rid):
    auth(["ProgramManager", "CredentialingOfficer", "Coach",
          "CompetitionDirector"], write=False)
    credential = derive.require("credentials", rid)
    return ok(ser_credential(credential))

# -------------------------------------------------------------- credentials ---


@bp.post("/volunteers/<rid>/credentials")
def create_credential(rid):
    auth(["CredentialingOfficer"])
    volunteer = derive.require("volunteers", rid)
    body = get_body()
    role_class = req_enum(body, "role_class", ROLE_CLASSES)
    if role_class == "COACH" and volunteer_is_minor(volunteer):
        fail("ERR_MINOR_CANNOT_BE_COACH", 422,
             "A volunteer under %d may not be credentialed as a coach."
             % ADULT_AGE_YEARS)
    if role_class != volunteer["volunteer_class"]:
        fail("ERR_ROLE_CLASS_MISMATCH", 422,
             "role_class must equal the volunteer's declared volunteer_class.")
    credential = db.new_row("credentials", {
        "volunteer_id": volunteer["id"],
        "role_class": role_class,
        "status": "INITIATED",
        "screening_result": None,
        "screening_completed_on": None,
        "screening_expires_on": None,
        "screening_recorded_by_user_id": None,
        "screening_vendor_reference": None,
        "training_completed_on": None,
        "training_expires_on": None,
        "training_recorded_by_user_id": None,
        "training_curriculum_code": None,
        "certified_by_user_id": None,
        "certified_at": None,
        "flag_override_reason": None,
        "expires_on": None,
        "denial_reason_code": None,
    })
    derive.recompute_program(derive.program_of_volunteer(volunteer))
    return ok(ser_credential(credential), 201)


@bp.post("/credentials/<rid>/screening")
def record_screening(rid):
    _role, user_id = auth(["CredentialingOfficer"])
    credential = derive.require("credentials", rid)
    body = get_body()
    completed_on = req_date_field(body, "completed_on")
    result = req_enum(body, "result", SCREENING_RESULTS)
    vendor_reference = req_str(body, "vendor_reference", 1, 120)
    if completed_on > clock_date():
        bad_request("completed_on may not fall after the logical clock date.")
    if credential["training_recorded_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", 403,
             "The user who recorded this credential's training may not record "
             "its screening.")
    status = credential["status"]
    renewal = False
    if status in RECORDABLE_FRESH_SCREENING:
        if credential["screening_result"] is not None:
            _step_conflict()
    elif status in RENEWAL_STATES:
        renewal = True
        previous = parse_date(credential["screening_completed_on"])
        if previous is not None and completed_on <= previous:
            _step_conflict()
    else:
        _step_conflict()

    volunteer = db.volunteers[credential["volunteer_id"]]
    program = derive.program_of_volunteer(volunteer)
    credential["screening_result"] = result
    credential["screening_completed_on"] = fmt_date(completed_on)
    credential["screening_vendor_reference"] = vendor_reference
    credential["screening_recorded_by_user_id"] = user_id
    if result == "DISQUALIFYING":
        credential["screening_expires_on"] = None
        credential["status"] = "DENIED"
        credential["denial_reason_code"] = "DISQUALIFYING_SCREENING"
        db.touch(credential)
        derive.void_sessions_for_credential(credential, "CREDENTIAL_DENIED")
        derive.recompute_teams_for_volunteer(volunteer)
    else:
        credential["screening_expires_on"] = fmt_date(
            add_days(completed_on, SCREENING_VALIDITY_DAYS))
        if renewal:
            credential["status"] = "RENEWAL_IN_PROGRESS"
        elif status == "TRAINING_COMPLETE":
            credential["status"] = "READY_TO_CERTIFY"
        else:
            credential["status"] = "SCREENING_CLEARED"
        db.touch(credential)
    derive.recompute_program(program)
    return ok(ser_credential(credential))


@bp.post("/credentials/<rid>/training")
def record_training(rid):
    _role, user_id = auth(["CredentialingOfficer"])
    credential = derive.require("credentials", rid)
    body = get_body()
    completed_on = req_date_field(body, "completed_on")
    curriculum_code = req_str(body, "curriculum_code", 1, 120)
    if completed_on > clock_date():
        bad_request("completed_on may not fall after the logical clock date.")
    if credential["screening_recorded_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", 403,
             "The user who recorded this credential's screening may not record "
             "its training.")
    status = credential["status"]
    renewal = False
    if status in RECORDABLE_FRESH_TRAINING:
        if credential["training_completed_on"] is not None:
            _step_conflict()
    elif status in RENEWAL_STATES:
        renewal = True
        previous = parse_date(credential["training_completed_on"])
        if previous is not None and completed_on <= previous:
            _step_conflict()
    else:
        _step_conflict()

    window = TRAINING_VALIDITY_DAYS_BY_ROLE[credential["role_class"]]
    credential["training_completed_on"] = fmt_date(completed_on)
    credential["training_curriculum_code"] = curriculum_code
    credential["training_recorded_by_user_id"] = user_id
    credential["training_expires_on"] = fmt_date(add_days(completed_on, window))
    if renewal:
        credential["status"] = "RENEWAL_IN_PROGRESS"
    elif status == "SCREENING_CLEARED":
        credential["status"] = "READY_TO_CERTIFY"
    else:
        credential["status"] = "TRAINING_COMPLETE"
    db.touch(credential)
    derive.recompute_program(derive.program_of_credential(credential))
    return ok(ser_credential(credential))


@bp.post("/credentials/<rid>/certify")
def certify_credential(rid):
    _role, user_id = auth(["CredentialingOfficer"])
    credential = derive.require("credentials", rid)
    body = get_body()
    flag_override_reason = opt_str(body, "flag_override_reason")
    if user_id in (credential["screening_recorded_by_user_id"],
                   credential["training_recorded_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES", 403,
             "The certifying user may not have recorded either branch of this "
             "credential.")
    if credential["status"] not in ("READY_TO_CERTIFY", "RENEWAL_IN_PROGRESS"):
        fail("ERR_CREDENTIAL_NOT_READY_TO_CERTIFY", 409,
             "This credential is not in a certifiable state.")
    today = clock_date()
    screening_expiry = parse_date(credential["screening_expires_on"])
    training_expiry = parse_date(credential["training_expires_on"])
    if (screening_expiry is None or training_expiry is None
            or screening_expiry < today or training_expiry < today):
        fail("ERR_CREDENTIAL_NOT_READY_TO_CERTIFY", 409,
             "A credential may not be certified on a lapsed branch.")
    if credential["screening_result"] == "FLAGGED" and (
            flag_override_reason is None or flag_override_reason.strip() == ""):
        fail("ERR_FLAG_OVERRIDE_REQUIRED", 422,
             "A flagged screening requires a non-empty flag_override_reason.")
    volunteer = db.volunteers[credential["volunteer_id"]]
    if credential["role_class"] == "COACH" and volunteer_is_minor(volunteer):
        fail("ERR_MINOR_CANNOT_BE_COACH", 422,
             "A volunteer under %d may not be certified as a coach."
             % ADULT_AGE_YEARS)

    expiry = min(screening_expiry, training_expiry)
    if credential["screening_result"] == "FLAGGED":
        expiry = min(expiry, add_days(today, FLAGGED_REVIEW_DAYS))
    credential["status"] = "CERTIFIED"
    credential["certified_by_user_id"] = user_id
    credential["certified_at"] = clock_str()
    credential["expires_on"] = fmt_date(expiry)
    if flag_override_reason is not None:
        credential["flag_override_reason"] = flag_override_reason
    db.touch(credential)
    derive.recompute_teams_for_volunteer(volunteer)
    derive.recompute_program(derive.program_of_volunteer(volunteer))
    return ok(ser_credential(credential))

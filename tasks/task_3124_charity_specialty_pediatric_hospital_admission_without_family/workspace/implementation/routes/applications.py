"""PatientApplication + ApplicationReview endpoints (PRD §3.2, §3.3)."""

from flask import Blueprint, request

import db
import services
from errors import (ApiError, ERR_APPLICATION_NOT_FOUND,
                    ERR_AGE_INELIGIBLE, ERR_CONDITION_OUT_OF_SCOPE,
                    ERR_CONVERSION_WINDOW_CLOSED,
                    ERR_HOSPITAL_CAPACITY_REACHED,
                    ERR_INTERNATIONAL_NOT_ACCEPTED, ERR_PROGRAM_NOT_ACTIVE,
                    ERR_QUORUM_NOT_MET, ERR_REVIEWER_CONFLICT,
                    ERR_SCREENING_MISMATCH, ERR_SCREENING_NOT_FOUND,
                    ERR_STALE_VERSION, bad_request, invalid_state)
from helpers import (get_body, iso_date, is_int, months_between, new_id,
                     now_iso, opt_enum, opt_int, opt_str, parse_dt, req_dt,
                     req_enum, req_num, req_str, touch)
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.programs import get_program_or_404
from routes.referral_sources import get_source_or_404
from views import application_view, review_view

bp = Blueprint("applications", __name__)

CONDITION_CATEGORIES = {"ORTHOPEDIC", "BURN", "CLEFT_CRANIOFACIAL",
                        "SPINAL_CORD", "NEUROMUSCULAR", "OTHER"}
ABILITY_TO_PAY = {"UNABLE", "PARTIAL", "ABLE", "DECLINED_TO_STATE"}

ACCEPT_QUORUM_WEIGHT = 3
DENY_QUORUM_WEIGHT = 2

LIST_ROLES = ["NetworkAdmin", "IntakeCoordinator", "ReviewCommitteeMember",
              "BillingSpecialist", "CareCoordinator", "OutreachPlanner",
              "PhilanthropyOfficer"]


def get_application_or_404(application_id):
    a = db.applications.get(application_id)
    if a is None:
        raise ApiError(ERR_APPLICATION_NOT_FOUND, 404, "Application id does not exist")
    return a


def _append_review(application, action, reviewer_user_id, vote_weight=None):
    now = now_iso()
    r = {
        "id": new_id(),
        "application_id": application["id"],
        "round_number": application["review_round"],
        "reviewer_user_id": reviewer_user_id,
        "action": action,
        "vote_weight": vote_weight if vote_weight is not None else 1,
        "created_at": now,
    }
    db.reviews[r["id"]] = r
    return r


@bp.post("/applications")
def create_application():
    user_id, role = require_auth(["IntakeCoordinator", "ReferringPhysician"])
    body = get_body()
    patient_full_name = req_str(body, "patient_full_name")
    dob = req_dt(body, "patient_date_of_birth")
    condition_category = req_enum(body, "condition_category", CONDITION_CATEGORIES)
    referral_source_id = body.get("referral_source_id")
    if referral_source_id is None:
        raise bad_request("Missing required field: referral_source_id")
    if not isinstance(referral_source_id, str) or referral_source_id == "":
        raise bad_request("Field referral_source_id must be a non-empty string")
    program_id = body.get("program_id")
    if program_id is None:
        raise bad_request("Missing required field: program_id")
    if not isinstance(program_id, str) or program_id == "":
        raise bad_request("Field program_id must be a non-empty string")
    home_latitude = req_num(body, "home_latitude")
    home_longitude = req_num(body, "home_longitude")
    family_ability_to_pay = opt_enum(body, "family_ability_to_pay",
                                     ABILITY_TO_PAY, "DECLINED_TO_STATE")
    screening_id = body.get("screening_id")
    if screening_id is not None and (not isinstance(screening_id, str) or screening_id == ""):
        raise bad_request("Field screening_id must be a non-empty string")

    # ReferringPhysician ownership: referral_source_id must equal the caller's X-User-ID
    if role == "ReferringPhysician" and referral_source_id != user_id:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "ReferringPhysician must submit under their own referral source id")

    # Body FK existence in declared input order: referral_source_id, program_id, screening_id
    source = get_source_or_404(referral_source_id)
    program = get_program_or_404(program_id)
    screening = None
    if screening_id is not None:
        screening = db.screenings.get(screening_id)
        if screening is None:
            raise ApiError(ERR_SCREENING_NOT_FOUND, 404, "Screening id does not exist")

    # Business rule ladder (PRD §3.2): scope -> age -> international -> screening linkage
    if condition_category == "OTHER" or condition_category != program["category"]:
        raise ApiError(ERR_CONDITION_OUT_OF_SCOPE, 422,
                       "Application condition_category does not match the program's category, or is OTHER")
    age_months = months_between(dob, db.CLOCK)
    if not (program["min_age_months"] <= age_months < program["max_age_months"]):
        raise ApiError(ERR_AGE_INELIGIBLE, 422,
                       "Patient age at submission outside [min_age_months, max_age_months) of the program")
    is_international = source["country_code"] != "US"
    if is_international and not program["accepts_international"]:
        raise ApiError(ERR_INTERNATIONAL_NOT_ACCEPTED, 422,
                       "International referral targeted a program with accepts_international == false")
    if screening is not None:
        clinic = db.clinics.get(screening["clinic_id"])
        hospital = db.hospitals.get(program["hospital_id"])
        if (screening["status"] != "COMPLETED"
                or clinic is None
                or hospital is None
                or clinic["hospital_id"] != hospital["id"]
                or screening["suspected_condition_category"] != condition_category):
            raise ApiError(ERR_SCREENING_MISMATCH, 422,
                           "screening_id references a screening of another hospital, "
                           "wrong condition category, or not COMPLETED")

    now = now_iso()
    a = {
        "id": new_id(),
        "patient_full_name": patient_full_name,
        "patient_date_of_birth": iso_date(dob),
        "condition_category": condition_category,
        "referral_source_id": referral_source_id,
        "program_id": program_id,
        "screening_id": screening_id,
        "home_latitude": home_latitude,
        "home_longitude": home_longitude,
        "is_international": is_international,
        "family_ability_to_pay": family_ability_to_pay,
        "review_round": 1,
        "info_requested_by": None,
        "decision_reason": None,
        "age_at_submission_months": age_months,
        "status": "SUBMITTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "accepted_at": None,
    }
    db.applications[a["id"]] = a
    return success_object(application_view(a), 201)


@bp.get("/applications")
def list_applications():
    require_auth(LIST_ROLES)
    items = list(db.applications.values())
    program_id = request.args.get("program_id")
    if program_id:
        items = [a for a in items if a["program_id"] == program_id]
    referral_source_id = request.args.get("referral_source_id")
    if referral_source_id:
        items = [a for a in items if a["referral_source_id"] == referral_source_id]
    screening_id = request.args.get("screening_id")
    if screening_id:
        items = [a for a in items if a.get("screening_id") == screening_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    condition_category = request.args.get("condition_category")
    if condition_category:
        items = [a for a in items if a["condition_category"] == condition_category]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([application_view(a) for a in page], total, limit, offset)


@bp.get("/applications/<applicationId>")
def get_application(applicationId):
    require_auth(LIST_ROLES)
    a = get_application_or_404(applicationId)
    return success_object(application_view(a))


@bp.post("/applications/<applicationId>/open-review")
def open_review(applicationId):
    user_id, _ = require_auth(["ReviewCommitteeMember"])
    a = get_application_or_404(applicationId)
    if a["status"] != "SUBMITTED":
        raise invalid_state("Application must be SUBMITTED to open review")
    a["status"] = "PENDING_REVIEW"
    touch(a)
    _append_review(a, "OPEN_ROUND", user_id)
    return success_object(application_view(a))


@bp.post("/applications/<applicationId>/request-info")
def request_info(applicationId):
    user_id, _ = require_auth(["ReviewCommitteeMember"])
    a = get_application_or_404(applicationId)
    if a["status"] != "PENDING_REVIEW":
        raise invalid_state("Application must be PENDING_REVIEW to request info")
    a["status"] = "INFO_REQUESTED"
    a["info_requested_by"] = user_id
    touch(a)
    _append_review(a, "REQUEST_INFO", user_id)
    return success_object(application_view(a))


@bp.post("/applications/<applicationId>/resubmit-info")
def resubmit_info(applicationId):
    user_id, _ = require_auth(["IntakeCoordinator"])
    a = get_application_or_404(applicationId)
    if a["status"] != "INFO_REQUESTED":
        raise invalid_state("Application must be INFO_REQUESTED to resubmit info")
    a["status"] = "PENDING_REVIEW"
    a["review_round"] += 1
    touch(a)
    _append_review(a, "RESUBMIT_INFO", user_id)
    return success_object(application_view(a))


@bp.post("/applications/<applicationId>/vote")
def vote(applicationId):
    user_id, _ = require_auth(["ReviewCommitteeMember"])
    a = get_application_or_404(applicationId)
    body = get_body()
    vote_value = req_enum(body, "vote", {"ACCEPT", "DENY"})
    vote_weight = opt_int(body, "vote_weight", 1, minimum=1)
    if a["status"] != "PENDING_REVIEW":
        raise invalid_state("Application must be PENDING_REVIEW to cast a vote")
    action = "CAST_VOTE_ACCEPT" if vote_value == "ACCEPT" else "CAST_VOTE_DENY"
    touch(a)
    r = _append_review(a, action, user_id, vote_weight)
    return success_object(review_view(r))


@bp.post("/applications/<applicationId>/decide")
def decide(applicationId):
    user_id, _ = require_auth(["ReviewCommitteeMember"])
    a = get_application_or_404(applicationId)
    body = get_body()
    decision = req_enum(body, "decision", {"ACCEPT", "DENY"})
    decision_reason = req_str(body, "decision_reason")
    expected_application_version = body.get("expected_application_version")
    if expected_application_version is None:
        raise bad_request("Missing required field: expected_application_version")
    if not is_int(expected_application_version):
        raise bad_request("Field expected_application_version must be an integer")

    # State check (priority 5) before OCC (priority 6)
    if a["status"] != "PENDING_REVIEW":
        raise invalid_state("Application must be PENDING_REVIEW to decide")
    if expected_application_version != a["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_application_version does not match the application's current version")

    # Decision-time checks in fixed order (PRD §3.3):
    # segregation of duties -> quorum -> hospital capacity -> program status
    if a.get("info_requested_by") is not None and a["info_requested_by"] == user_id:
        raise ApiError(ERR_REVIEWER_CONFLICT, 403,
                       "Deciding member is the member who requested info on the current round")

    round_reviews = [r for r in db.reviews.values()
                     if r["application_id"] == a["id"]
                     and r["round_number"] == a["review_round"]]
    accept_weight = sum(r["vote_weight"] for r in round_reviews
                        if r["action"] == "CAST_VOTE_ACCEPT")
    deny_weight = sum(r["vote_weight"] for r in round_reviews
                      if r["action"] == "CAST_VOTE_DENY")
    if decision == "ACCEPT":
        if accept_weight < ACCEPT_QUORUM_WEIGHT or deny_weight != 0:
            raise ApiError(ERR_QUORUM_NOT_MET, 409,
                           "Weighted vote quorum on the current round not met, "
                           "or both accept and deny weights nonzero")
    else:
        if deny_weight < DENY_QUORUM_WEIGHT or accept_weight != 0:
            raise ApiError(ERR_QUORUM_NOT_MET, 409,
                           "Weighted vote quorum on the current round not met, "
                           "or both accept and deny weights nonzero")

    program = db.programs.get(a["program_id"])
    hospital = db.hospitals.get(program["hospital_id"]) if program else None

    if decision == "ACCEPT":
        if hospital["admissions_ytd"] >= hospital["annual_capacity"]:
            raise ApiError(ERR_HOSPITAL_CAPACITY_REACHED, 409,
                           "Hospital admissions_ytd == annual_capacity; "
                           "no more acceptances this calendar year")
        if program["status"] != "ACTIVE":
            raise ApiError(ERR_PROGRAM_NOT_ACTIVE, 409,
                           "Program must be ACTIVE for acceptance")
        # Screening conversion window (PRD §3.8): conversion at exactly the deadline
        # succeeds; past the deadline the acceptance is rejected.
        if a.get("screening_id"):
            screening = db.screenings.get(a["screening_id"])
            if screening is not None and screening["status"] != "CONVERTED":
                clinic = db.clinics.get(screening["clinic_id"])
                if clinic is not None and db.CLOCK > parse_dt(clinic["conversion_deadline"]):
                    raise ApiError(ERR_CONVERSION_WINDOW_CLOSED, 409,
                                   "Screening conversion attempted after conversion_deadline")

    # --- Commit the decision ---
    a["decision_reason"] = decision_reason
    a["status"] = "ACCEPTED" if decision == "ACCEPT" else "DENIED"
    touch(a)
    _append_review(a, "CAST_VOTE_ACCEPT" if decision == "ACCEPT" else "CAST_VOTE_DENY",
                   user_id)

    if decision == "ACCEPT":
        a["accepted_at"] = db.CLOCK
        hospital["admissions_ytd"] += 1
        touch(hospital)

        # Auto-create the BillingAccount (PRD §3.4)
        policy = None
        for p in db.policies.values():
            if p["application_id"] == a["id"] and p["coverage_exists"]:
                policy = p
                break
        now = now_iso()
        account = {
            "id": new_id(),
            "application_id": a["id"],
            "insurance_policy_id": policy["id"] if policy else None,
            "total_charged_cents": 0,
            "insurance_paid_cents": 0,
            "charity_writeoff_cents": 0,
            "family_balance_cents": 0,
            "open_claim_cents": 0,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.billing_accounts[account["id"]] = account

        # Auto-create the CarePlan when staged care is required (PRD §3.6)
        if program["staged_care_required"]:
            plan = {
                "id": new_id(),
                "application_id": a["id"],
                "diagnosis_summary": None,
                "clinical_status": "PLANNING",
                "funding_status": "UNFUNDED",
                "planned_stage_count": 0,
                "completed_stage_count": 0,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            db.care_plans[plan["id"]] = plan

        # Convert the linked screening (PRD §3.8)
        if a.get("screening_id"):
            screening = db.screenings.get(a["screening_id"])
            if screening is not None and screening["status"] == "COMPLETED":
                screening["status"] = "CONVERTED"
                screening["converted_application_id"] = a["id"]
                touch(screening)

    return success_object(application_view(a))


@bp.post("/applications/<applicationId>/withdraw")
def withdraw(applicationId):
    require_auth(["IntakeCoordinator"])
    a = get_application_or_404(applicationId)
    if a["status"] not in ("SUBMITTED", "PENDING_REVIEW", "INFO_REQUESTED"):
        raise invalid_state("Application must be SUBMITTED, PENDING_REVIEW, "
                            "or INFO_REQUESTED to withdraw")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success_object(application_view(a))


@bp.get("/applications/<id>/reviews")
def list_reviews(id):
    require_auth(["NetworkAdmin", "IntakeCoordinator", "ReviewCommitteeMember"])
    a = get_application_or_404(id)
    items = [r for r in db.reviews.values() if r["application_id"] == a["id"]]
    round_number = request.args.get("round_number")
    if round_number is not None and round_number != "":
        try:
            rn = int(round_number)
        except ValueError:
            raise bad_request("round_number must be an integer")
        items = [r for r in items if r["round_number"] == rn]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([review_view(r) for r in page], total, limit, offset)

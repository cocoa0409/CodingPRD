"""Application endpoints: create, list, get, submit, withdraw."""
from flask import Blueprint, request

import clock
import serializers
import store
from auth import forbid, identity, require_roles
from calculations import (
    academic_eligible,
    academic_index,
    compute_prep_alum,
    income_eligible,
    need_tier,
)
from errors import (
    ApiError,
    ERR_ACADEMIC_INELIGIBLE,
    ERR_DUPLICATE_APPLICATION,
    ERR_INCOME_INELIGIBLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MATCH_BINDING,
    ERR_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_WINDOW_CLOSED,
    ERR_WRONG_CYCLE_PHASE,
)
from response import ok_object, paginated
from validation import KIND_INT, KIND_STR, get_body, validate

bp = Blueprint("applications", __name__)

WITHDRAWABLE_STATUSES = ("DRAFT", "UNDER_REVIEW", "FINALIST", "RANKING_SUBMITTED", "REGULAR_POOL")
VOIDABLE_PACKAGE_STATUSES = ("PROVISIONAL", "FINALIZED", "REVISED")


def get_application_or_404(application_id):
    application = store.applications.get(application_id)
    if application is None:
        raise ApiError(ERR_NOT_FOUND, "application not found")
    return application


def require_own_application(role, uid, application):
    if role == "Student" and uid != application["student_id"]:
        forbid("a student may only act on their own applications")


def void_application_packages(application_id):
    for package in store.aid_packages.values():
        if package["application_id"] == application_id and package["status"] in VOIDABLE_PACKAGE_STATUSES:
            package["status"] = "VOID"
            store.touch(package)


@bp.post("/applications")
def create_application():
    body = get_body()
    values = validate(body, [
        ("cycle_id", KIND_STR, True, None, None),
        ("referral_id", KIND_STR, False, None, None),
        ("household_income_cents", KIND_INT, True, None, None),
        ("household_size", KIND_INT, True, None, None),
        ("self_reported_assets_cents", KIND_INT, False, 0, None),
        ("gpa_scaled", KIND_INT, True, None, None),
        ("test_score", KIND_INT, False, None, None),
        ("essay_text", KIND_STR, False, "", None),
    ])
    role, uid = identity()
    require_roles(role, ("Student",))
    if values["household_size"] < 1:
        raise ApiError(ERR_INVALID_REQUEST, "household_size must be >= 1")
    # student_id is taken from the caller's X-User-ID, never from the payload.
    cycle = store.cycles.get(values["cycle_id"])
    if cycle is None:
        raise ApiError(ERR_NOT_FOUND, "cycle not found")
    if cycle["phase"] != "APPLICATION_OPEN":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "application creation is permitted only in APPLICATION_OPEN")
    if values["referral_id"] is not None:
        referral = store.referrals.get(values["referral_id"])
        if (referral is None
                or referral["status"] != "NOMINATED"
                or referral["student_id"] != uid
                or referral["cycle_id"] != values["cycle_id"]):
            raise ApiError(
                ERR_REFERRAL_NOT_FOUND,
                "referral_id does not exist, is not NOMINATED, or belongs to a different student or cycle",
            )
    for existing in store.applications.values():
        if (existing["student_id"] == uid
                and existing["cycle_id"] == values["cycle_id"]
                and existing["status"] != "WITHDRAWN"):
            raise ApiError(ERR_DUPLICATE_APPLICATION, "student already has a non-WITHDRAWN application in this cycle")
    application = store.create(store.applications, {
        "student_id": uid,
        "cycle_id": values["cycle_id"],
        "referral_id": values["referral_id"],
        "household_income_cents": values["household_income_cents"],
        "household_size": values["household_size"],
        "self_reported_assets_cents": values["self_reported_assets_cents"],
        "gpa_scaled": values["gpa_scaled"],
        "test_score": values["test_score"],
        "essay_text": values["essay_text"],
        "status": "DRAFT",
        "academic_index": None,
        "prep_alum": False,
        "need_tier": None,
        "verification_flag": "NONE",
        "matched_college_id": None,
        "submitted_at": None,
    })
    return ok_object(serializers.application(application), 201)


@bp.get("/applications")
def list_applications():
    role, _ = identity()
    require_roles(role, ("ProgramAdmin", "CollegeOfficer", "Counselor", "PartnerStaff"))
    items = list(store.applications.values())
    for field in ("student_id", "cycle_id", "referral_id", "matched_college_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [a for a in items if a[field] == value]
    items.sort(key=lambda a: a["created_at"])
    return paginated(items, serializers.application)


@bp.get("/applications/<application_id>")
def get_application(application_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "Student", "CollegeOfficer", "Counselor"))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    return ok_object(serializers.application(application))


@bp.post("/applications/<application_id>/submit")
def submit_application(application_id):
    role, uid = identity()
    require_roles(role, ("Student",))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    # Guards fire in the global order of PRD section 2.10.
    if application["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "only a DRAFT application can be submitted")
    cycle = store.cycles.get(application["cycle_id"])
    if cycle is None or cycle["phase"] != "APPLICATION_OPEN":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "submission is permitted only in APPLICATION_OPEN")
    now = clock.now()
    if now < cycle["app_opens_at"] or now > cycle["app_closes_at"]:
        raise ApiError(ERR_WINDOW_CLOSED, "outside the application window")
    # Snapshot: prep_alum is true exactly when the student has a COMPLETED
    # prep record at this moment.
    prep_alum = compute_prep_alum(application["student_id"])
    # The academic screen runs before the income screen.
    if not academic_eligible(prep_alum, application["gpa_scaled"], application["test_score"]):
        raise ApiError(ERR_ACADEMIC_INELIGIBLE, "application fails the academic eligibility screen")
    if not income_eligible(application["household_income_cents"], application["household_size"]):
        raise ApiError(ERR_INCOME_INELIGIBLE, "household income exceeds the size-adjusted cap")

    application["prep_alum"] = prep_alum
    application["academic_index"] = academic_index(application["gpa_scaled"], application["test_score"])
    application["need_tier"] = need_tier(application["household_income_cents"], application["household_size"])
    application["submitted_at"] = now
    application["status"] = "UNDER_REVIEW"
    store.touch(application)

    # A cited NOMINATED referral flips to CONVERTED.
    if application["referral_id"]:
        referral = store.referrals.get(application["referral_id"])
        if referral is not None and referral["status"] == "NOMINATED":
            referral["status"] = "CONVERTED"
            store.touch(referral)

    student = store.students.get(application["student_id"])
    if student is not None:
        student["student_stage"] = "APPLICANT"
        store.touch(student)
    return ok_object(serializers.application(application))


@bp.post("/applications/<application_id>/withdraw")
def withdraw_application(application_id):
    role, uid = identity()
    require_roles(role, ("Student",))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    # MATCHED is binding: withdrawal is rejected with ERR_MATCH_BINDING.
    if application["status"] == "MATCHED":
        raise ApiError(ERR_MATCH_BINDING, "the match is binding")
    if application["status"] not in WITHDRAWABLE_STATUSES:
        raise ApiError(ERR_INVALID_STATE, "application cannot be withdrawn from its current state")
    void_application_packages(application["id"])
    application["status"] = "WITHDRAWN"
    store.touch(application)
    return ok_object(serializers.application(application))

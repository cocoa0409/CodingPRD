"""Match endpoints: get, list, release (compensation cascade), enroll."""
from flask import Blueprint, request

import clock
import serializers
import store
from auth import forbid, identity, require_roles
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_WRONG_CYCLE_PHASE
from response import ok_object, paginated
from validation import KIND_STR, get_body, validate

bp = Blueprint("matches", __name__)

READ_ROLES = ("ProgramAdmin", "Student", "CollegeOfficer")
ENROLL_PHASES = ("REGULAR_DECISION", "OUTCOME_TRACKING")
VOIDABLE_PACKAGE_STATUSES = ("PROVISIONAL", "FINALIZED", "REVISED")


def get_match_or_404(match_id):
    match = store.matches.get(match_id)
    if match is None:
        raise ApiError(ERR_NOT_FOUND, "match not found")
    return match


def check_match_ownership(role, uid, match):
    if role == "CollegeOfficer" and match["college_id"] != uid:
        forbid("a college officer may only act on their own college's matches")
    if role == "Student":
        application = store.applications.get(match["application_id"])
        if application is None or application["student_id"] != uid:
            forbid("a student may only view their own matches")


@bp.get("/matches")
def list_matches():
    role, _ = identity()
    require_roles(role, READ_ROLES)
    items = list(store.matches.values())
    for field in ("application_id", "college_id", "cycle_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [m for m in items if m[field] == value]
    items.sort(key=lambda m: m["created_at"])
    return paginated(items, serializers.match)


@bp.get("/matches/<match_id>")
def get_match(match_id):
    role, uid = identity()
    require_roles(role, READ_ROLES)
    match = get_match_or_404(match_id)
    check_match_ownership(role, uid, match)
    return ok_object(serializers.match(match))


@bp.post("/matches/<match_id>/release")
def release_match(match_id):
    body = get_body()
    validate(body, [("reason", KIND_STR, False, None, None)])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    match = get_match_or_404(match_id)
    if match["status"] != "BINDING":
        raise ApiError(ERR_INVALID_STATE, "only a BINDING match can be released")

    # Four-link release cascade (PRD section 3.8).
    # Link 1: the match itself.
    match["status"] = "RELEASED"
    store.touch(match)
    # Link 2: void the match's live aid package; the freed slot returns to the
    # pool (slots_committed is computed from BINDING/ENROLLED matches).
    for package in store.aid_packages.values():
        if package["match_id"] == match["id"] and package["status"] in VOIDABLE_PACKAGE_STATUSES:
            package["status"] = "VOID"
            store.touch(package)
    # Link 3: the application rejoins the regular pool with the match link cleared.
    application = store.applications.get(match["application_id"])
    if application is not None and application["status"] == "MATCHED":
        application["status"] = "REGULAR_POOL"
        application["matched_college_id"] = None
        store.touch(application)
        # Link 4: the student falls back to FINALIST.
        student = store.students.get(application["student_id"])
        if student is not None:
            student["student_stage"] = "FINALIST"
            store.touch(student)
    return ok_object(serializers.match(match))


@bp.post("/matches/<match_id>/enroll")
def enroll_match(match_id):
    role, uid = identity()
    require_roles(role, ("CollegeOfficer", "ProgramAdmin"))
    match = get_match_or_404(match_id)
    if role == "CollegeOfficer" and match["college_id"] != uid:
        forbid("a college officer may only enroll their own college's matches")
    if match["status"] != "BINDING":
        raise ApiError(ERR_INVALID_STATE, "only a BINDING match can be enrolled")
    cycle = store.cycles.get(match["cycle_id"])
    if cycle is None or cycle["phase"] not in ENROLL_PHASES:
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "enrollment is permitted only in REGULAR_DECISION or OUTCOME_TRACKING")

    store.create(store.outcomes, {
        "application_id": match["application_id"],
        "college_id": match["college_id"],
        "cycle_id": match["cycle_id"],
        "match_id": match["id"],
        "status": "ENROLLED_Y1",
        "credits_completed": 0,
        "last_checkpoint_at": clock.now(),
    })
    match["status"] = "ENROLLED"
    store.touch(match)
    application = store.applications.get(match["application_id"])
    if application is not None:
        application["status"] = "ENROLLED"
        store.touch(application)
        student = store.students.get(application["student_id"])
        if student is not None:
            student["student_stage"] = "ENROLLED"
            store.touch(student)
    return ok_object(serializers.match(match))

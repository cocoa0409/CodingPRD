"""Application action endpoints: review, rankings (submit/read), the per-app
income-verification listing, regular-decision, and regular-path enroll."""
from flask import Blueprint

import clock
import serializers
import store
from auth import identity, require_roles
from calculations import MAX_RANKS, create_package, latest_list_seq
from errors import (
    ApiError,
    ERR_COLLEGE_INACTIVE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RANK_ORDER_INVALID,
    ERR_STALE_VERSION,
    ERR_TOO_MANY_RANKS,
    ERR_UNKNOWN_COLLEGE,
    ERR_WINDOW_CLOSED,
    ERR_WRONG_CYCLE_PHASE,
)
from response import ok_object, paginated
from routes.applications import get_application_or_404, require_own_application
from validation import KIND_ENUM, get_body, is_int, validate

bp = Blueprint("application_actions", __name__)

REVIEW_DECISIONS = ("FINALIST", "NOT_FINALIST")
REGULAR_DECISIONS = ("ADMIT", "DENY")
ENROLL_PHASES = ("REGULAR_DECISION", "OUTCOME_TRACKING")
LIVE_PACKAGE_STATUSES = ("PROVISIONAL", "FINALIZED", "REVISED")


@bp.post("/applications/<application_id>/review")
def review_application(application_id):
    body = get_body()
    values = validate(body, [("decision", KIND_ENUM, True, None, REVIEW_DECISIONS)])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    application = get_application_or_404(application_id)
    if application["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "only an UNDER_REVIEW application can be reviewed")
    cycle = store.cycles.get(application["cycle_id"])
    if cycle is None or cycle["phase"] != "REVIEW":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "review is permitted only in REVIEW")
    application["status"] = values["decision"]
    store.touch(application)
    if values["decision"] == "FINALIST":
        student = store.students.get(application["student_id"])
        if student is not None:
            student["student_stage"] = "FINALIST"
            store.touch(student)
    return ok_object(serializers.application(application))


def _validate_entries_shape(body):
    """Priority 1 shape checks for the ranking submission payload."""
    entries = body.get("entries")
    if not isinstance(entries, list) or len(entries) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "entries must be a non-empty array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each ranking entry must be an object")
        college_id = entry.get("college_id")
        rank_position = entry.get("rank_position")
        if not isinstance(college_id, str):
            raise ApiError(ERR_INVALID_REQUEST, "entry.college_id must be a string")
        if not is_int(rank_position):
            raise ApiError(ERR_INVALID_REQUEST, "entry.rank_position must be an integer")
    expected = body.get("expected_application_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, "expected_application_version is required and must be an integer")
    return entries, expected


@bp.post("/applications/<application_id>/rankings")
def submit_rankings(application_id):
    body = get_body()
    entries, expected_version = _validate_entries_shape(body)
    role, uid = identity()
    require_roles(role, ("Student",))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    # Guards fire in the global order narrated by PRD section 3.4.
    if application["status"] not in ("FINALIST", "RANKING_SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, "application is not accepting ranking submissions")
    cycle = store.cycles.get(application["cycle_id"])
    if cycle is None or cycle["phase"] != "RANKING":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "rankings are permitted only in RANKING")
    now = clock.now()
    if now < cycle["ranking_opens_at"] or now > cycle["ranking_closes_at"]:
        raise ApiError(ERR_WINDOW_CLOSED, "outside the ranking window")
    if expected_version != application["version"]:
        raise ApiError(ERR_STALE_VERSION, "the application version has advanced since the caller last read it")
    for entry in entries:
        if entry["college_id"] not in store.colleges:
            raise ApiError(ERR_UNKNOWN_COLLEGE, "a college_id in the ranking list does not exist")
    for entry in entries:
        if store.colleges[entry["college_id"]]["status"] != "ACTIVE":
            raise ApiError(ERR_COLLEGE_INACTIVE, "a ranked college is not ACTIVE")
    count = len(entries)
    if count > MAX_RANKS:
        raise ApiError(ERR_TOO_MANY_RANKS, "ranking list exceeds 12 entries")
    positions = sorted(e["rank_position"] for e in entries)
    if positions != list(range(1, count + 1)):
        raise ApiError(ERR_RANK_ORDER_INVALID, "rank positions must be exactly 1..N, unique")
    college_ids = [e["college_id"] for e in entries]
    if len(set(college_ids)) != count:
        raise ApiError(ERR_RANK_ORDER_INVALID, "a college may appear at most once per list")

    # Atomic replace: the previous list is superseded wholesale (never edited
    # row by row). The old rows are retained -- the per-college listing
    # exposes every ranking row across all submissions, past and present
    # (PRD section 3.4) -- while the application's own list read filters to
    # the greatest list_seq.
    prior_seq = latest_list_seq(application["id"])
    for entry in sorted(entries, key=lambda e: e["rank_position"]):
        store.create(store.ranking_entries, {
            "application_id": application["id"],
            "college_id": entry["college_id"],
            "rank_position": entry["rank_position"],
            "list_seq": prior_seq + 1,
        }, common=False)
    application["status"] = "RANKING_SUBMITTED"
    store.touch(application)
    return ok_object(serializers.application(application))


@bp.get("/applications/<application_id>/rankings")
def get_rankings(application_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "Student", "CollegeOfficer"))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    seq = latest_list_seq(application["id"])
    items = sorted(
        (e for e in store.ranking_entries.values()
         if e["application_id"] == application["id"] and e["list_seq"] == seq),
        key=lambda e: e["rank_position"],
    )
    return paginated(items, serializers.ranking_entry)


@bp.get("/applications/<application_id>/income-verifications")
def get_income_verifications(application_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "PartnerStaff", "Counselor", "Student"))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    items = [v for v in store.verifications.values() if v["application_id"] == application["id"]]
    items.sort(key=lambda v: v["created_at"])
    return paginated(items, serializers.verification)


@bp.post("/applications/<application_id>/regular-decision")
def regular_decision(application_id):
    body = get_body()
    values = validate(body, [("decision", KIND_ENUM, True, None, REGULAR_DECISIONS)])
    role, uid = identity()
    require_roles(role, ("CollegeOfficer",))
    application = get_application_or_404(application_id)
    if application["status"] != "REGULAR_POOL":
        raise ApiError(ERR_INVALID_STATE, "only a REGULAR_POOL application can receive a regular decision")
    cycle = store.cycles.get(application["cycle_id"])
    if cycle is None or cycle["phase"] != "REGULAR_DECISION":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "regular decisions are permitted only in REGULAR_DECISION")
    if values["decision"] == "ADMIT":
        # The officer acts on behalf of their own college (X-User-ID), which
        # must be ACTIVE.
        college = store.colleges.get(uid)
        if college is None or college["status"] != "ACTIVE":
            raise ApiError(ERR_COLLEGE_INACTIVE, "the acting college is not ACTIVE")
        create_package(None, application, college, False)
        application["status"] = "ADMITTED_REGULAR"
    else:
        application["status"] = "REGULAR_DENIED"
    store.touch(application)
    return ok_object(serializers.application(application))


@bp.post("/applications/<application_id>/enroll")
def enroll_application(application_id):
    role, uid = identity()
    require_roles(role, ("Student",))
    application = get_application_or_404(application_id)
    require_own_application(role, uid, application)
    if application["status"] != "ADMITTED_REGULAR":
        raise ApiError(ERR_INVALID_STATE, "only an ADMITTED_REGULAR application can be enrolled")
    package = _latest_live_package(application["id"])
    if package is None:
        raise ApiError(ERR_INVALID_STATE, "no live aid package exists for this application")
    cycle = store.cycles.get(application["cycle_id"])
    if cycle is None or cycle["phase"] not in ENROLL_PHASES:
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "enrollment is permitted only in REGULAR_DECISION or OUTCOME_TRACKING")
    # The acceptance creates the outcome record with college and cycle taken
    # from the package (match_id null on the regular path).
    store.create(store.outcomes, {
        "application_id": application["id"],
        "college_id": package["college_id"],
        "cycle_id": application["cycle_id"],
        "match_id": None,
        "status": "ENROLLED_Y1",
        "credits_completed": 0,
        "last_checkpoint_at": clock.now(),
    })
    application["status"] = "ENROLLED"
    store.touch(application)
    student = store.students.get(application["student_id"])
    if student is not None:
        student["student_stage"] = "ENROLLED"
        store.touch(student)
    return ok_object(serializers.application(application))


def _latest_live_package(application_id):
    packages = [
        p for p in store.aid_packages.values()
        if p["application_id"] == application_id and p["status"] in LIVE_PACKAGE_STATUSES
    ]
    if not packages:
        return None
    packages.sort(key=lambda p: p["created_at"])
    return packages[-1]

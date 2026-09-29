"""Participant endpoints — PRD sections 3.1, 3.2 and 3.9."""

from flask import Blueprint

from cascades import apply_exit_cascade, apply_suspension_cascade
from common import list_result, match_filters, READ_ROLES, resolve
from domain import (
    DOCUMENT_TYPES, DOMAIN_SCORE_KEYS, EXIT_REASONS, HEALTH_COVERAGE_TARGETS,
    HOUSING_PLAN_TYPES, LICENSE_RELIEF_STATES, PETITION_MAX_ROUNDS,
    RECORD_CATEGORIES, SUSPENSION_TO_STATUSES, TRANSPORTATION_PLAN_TYPES,
    active_placement_count_of_participant, as_date, evaluate_readiness,
    readiness_met, recompute_barrier, recompute_doc_completeness,
    recompute_posture, rows,
)
from envelope import created, ok
from errors import fail
from store import db, new_row, now, public, touch
from validation import (
    body, caller_id, opt_date, opt_enum_array, opt_str, present, req_date,
    req_enum, req_enum_array, req_int, req_state_code, req_str, require_roles,
)

bp = Blueprint("participants", __name__)

WRITE_ROLE = ["CaseManager"]


def _validate_domain_scores(payload):
    if "assessment_domain_scores" not in payload or payload[
            "assessment_domain_scores"] is None:
        fail("ERR_VALIDATION", "assessment_domain_scores is required")
    scores = payload["assessment_domain_scores"]
    if not isinstance(scores, dict):
        fail("ERR_VALIDATION", "assessment_domain_scores must be an object")
    if set(scores.keys()) != set(DOMAIN_SCORE_KEYS):
        fail("ERR_VALIDATION",
             "assessment_domain_scores must carry exactly the five domain keys")
    cleaned = {}
    for key in DOMAIN_SCORE_KEYS:
        value = scores[key]
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_VALIDATION", "%s must be an integer" % key)
        if value < 0 or value > 4:
            fail("ERR_VALIDATION", "%s must be between 0 and 4" % key)
        cleaned[key] = value
    return cleaned


def _require_not_exited(participant):
    if participant["stage"] == "EXITED":
        fail("ERR_PARTICIPANT_INVALID_STATE",
             "An exited participant is frozen against direct writes")


# --------------------------------------------------------------------------
# create / read / list / update
# --------------------------------------------------------------------------

@bp.post("/participants")
def create_participant():
    require_roles(WRITE_ROLE)
    payload = body()
    full_name = req_str(payload, "full_name", min_len=1, max_len=120)
    facility_name = req_str(payload, "facility_name")
    facility_state = req_state_code(payload, "facility_state")
    req_date(payload, "expected_release_date")
    record_categories = req_enum_array(payload, "record_categories",
                                       RECORD_CATEGORIES)
    required_documents = req_enum_array(payload, "required_document_types",
                                        DOCUMENT_TYPES)
    case_manager = opt_str(payload, "assigned_case_manager_user_id")

    row = new_row(
        full_name=full_name,
        facility_name=facility_name,
        facility_state=facility_state,
        expected_release_date=payload["expected_release_date"],
        actual_release_date=None,
        record_categories=record_categories,
        required_document_types=required_documents,
        verified_document_types=[],
        doc_completeness_pct=0.0,
        assessment_domain_scores=None,
        barrier_score=None,
        barrier_tier=None,
        housing_plan_type=None,
        transportation_plan_type=None,
        health_coverage_target=None,
        planned_release_date=None,
        release_plan_status="NONE",
        release_plan_revision=0,
        stage="PRE_RELEASE",
        suspension_status="NONE",
        suspension_reason=None,
        license_relief_status="NONE",
        license_relief_occupation_code=None,
        petition_rounds_used=0,
        engagement_posture="OPEN",
        exit_reason=None,
        exit_date=None,
        assigned_case_manager_user_id=case_manager,
    )
    db.participants[row["id"]] = row
    return created(public(row))


@bp.get("/participants/<participant_id>")
def read_participant(participant_id):
    require_roles(READ_ROLES)
    participant = resolve("participants", db.participants, participant_id)
    return ok(public(participant))


@bp.get("/participants")
def list_participants():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.participants),
        string_filters=["stage", "barrier_tier", "engagement_posture",
                        "facility_state"],
    )
    return list_result(result)


@bp.put("/participants/<participant_id>")
def update_participant(participant_id):
    require_roles(WRITE_ROLE)
    payload = body()
    if present(payload, "full_name"):
        req_str(payload, "full_name", min_len=1, max_len=120)
    if present(payload, "facility_name"):
        req_str(payload, "facility_name")
    if present(payload, "facility_state"):
        req_state_code(payload, "facility_state")
    if present(payload, "expected_release_date"):
        req_date(payload, "expected_release_date")
    if present(payload, "record_categories"):
        req_enum_array(payload, "record_categories", RECORD_CATEGORIES)
    if present(payload, "required_document_types"):
        req_enum_array(payload, "required_document_types", DOCUMENT_TYPES)

    participant = resolve("participants", db.participants, participant_id)
    _require_not_exited(participant)

    for field in ("full_name", "facility_name", "facility_state",
                  "expected_release_date", "record_categories"):
        if present(payload, field):
            participant[field] = payload[field]
    if present(payload, "required_document_types"):
        participant["required_document_types"] = list(
            payload["required_document_types"])
        participant["verified_document_types"] = [
            t for t in participant["verified_document_types"]
            if t in participant["required_document_types"]]
        recompute_doc_completeness(participant)
        recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


# --------------------------------------------------------------------------
# assessment and documents
# --------------------------------------------------------------------------

@bp.post("/participants/<participant_id>/assessment")
def record_assessment(participant_id):
    require_roles(WRITE_ROLE)
    payload = body()
    scores = _validate_domain_scores(payload)

    participant = resolve("participants", db.participants, participant_id)
    _require_not_exited(participant)

    participant["assessment_domain_scores"] = scores
    recompute_barrier(participant)
    evaluate_readiness(participant)
    recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


@bp.post("/participants/<participant_id>/document-verifications")
def verify_document(participant_id):
    require_roles(WRITE_ROLE)
    payload = body()
    document_type = req_enum(payload, "document_type", DOCUMENT_TYPES)

    participant = resolve("participants", db.participants, participant_id)
    _require_not_exited(participant)

    if document_type not in (participant["required_document_types"] or []):
        fail("ERR_DOCUMENT_NOT_REQUIRED",
             "This document type is not required for this participant")
    if document_type in (participant["verified_document_types"] or []):
        fail("ERR_DOCUMENT_NOT_REQUIRED",
             "This document type is already verified")

    participant["verified_document_types"] = list(
        participant["verified_document_types"]) + [document_type]
    recompute_doc_completeness(participant)
    evaluate_readiness(participant)
    recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


# --------------------------------------------------------------------------
# release planning
# --------------------------------------------------------------------------

@bp.put("/participants/<participant_id>/release-plan")
def store_release_plan(participant_id):
    require_roles(WRITE_ROLE)
    payload = body()
    expected_version = req_int(payload, "expected_participant_version")
    housing = req_enum(payload, "housing_plan_type", HOUSING_PLAN_TYPES)
    transportation = req_enum(payload, "transportation_plan_type",
                              TRANSPORTATION_PLAN_TYPES)
    coverage = req_enum(payload, "health_coverage_target",
                        HEALTH_COVERAGE_TARGETS)
    req_date(payload, "planned_release_date")

    participant = resolve("participants", db.participants, participant_id)
    if expected_version != participant["version"]:
        fail("ERR_STALE_PARTICIPANT_VERSION",
             "The participant has been modified since it was last read")
    _require_not_exited(participant)

    participant["housing_plan_type"] = housing
    participant["transportation_plan_type"] = transportation
    participant["health_coverage_target"] = coverage
    participant["planned_release_date"] = payload["planned_release_date"]
    participant["release_plan_revision"] = int(
        participant["release_plan_revision"]) + 1
    participant["release_plan_status"] = "DRAFT"
    if participant["stage"] == "RELEASE_READY":
        participant["stage"] = "PRE_RELEASE"
    recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


@bp.post("/participants/<participant_id>/release-plan/approve")
def approve_release_plan(participant_id):
    require_roles(["ProgramDirector"])
    participant = resolve("participants", db.participants, participant_id)
    if participant["release_plan_status"] in ("NONE", "APPROVED"):
        fail("ERR_PARTICIPANT_INVALID_STATE",
             "There is no draft release plan to approve")
    participant["release_plan_status"] = "APPROVED"
    evaluate_readiness(participant)
    recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


@bp.post("/participants/<participant_id>/release")
def record_release(participant_id):
    require_roles(WRITE_ROLE)
    payload = body()
    release_date = req_date(payload, "actual_release_date")

    participant = resolve("participants", db.participants, participant_id)
    if participant["stage"] != "RELEASE_READY":
        fail("ERR_PARTICIPANT_INVALID_STATE",
             "Only a RELEASE_READY participant may be released")
    if participant["suspension_status"] != "NONE":
        fail("ERR_PARTICIPANT_INVALID_STATE",
             "A suspended participant may not be released")
    if release_date > now().date():
        fail("ERR_VALIDATION", "actual_release_date may not be in the future")

    participant["actual_release_date"] = payload["actual_release_date"]
    participant["stage"] = "POST_RELEASE"
    recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


# --------------------------------------------------------------------------
# suspension, licence relief and exit
# --------------------------------------------------------------------------

@bp.post("/participants/<participant_id>/suspension")
def drive_suspension(participant_id):
    require_roles(["ProgramDirector"])
    payload = body()
    to_status = req_enum(payload, "to_status", SUSPENSION_TO_STATUSES)
    reason = opt_str(payload, "suspension_reason")

    participant = resolve("participants", db.participants, participant_id)
    _require_not_exited(participant)

    if to_status == "SUSPENDED":
        if participant["suspension_status"] != "NONE":
            fail("ERR_PARTICIPANT_INVALID_STATE",
                 "The participant is already suspended")
        participant["suspension_status"] = "SUSPENDED"
        participant["suspension_reason"] = reason
        recompute_posture(participant)
        touch(participant)
        apply_suspension_cascade(participant)
    else:
        if participant["suspension_status"] != "SUSPENDED":
            fail("ERR_PARTICIPANT_INVALID_STATE",
                 "The participant is not suspended")
        participant["suspension_status"] = "NONE"
        participant["suspension_reason"] = None
        recompute_posture(participant)
        touch(participant)
    return ok(public(participant))


LICENSE_EDGES = {
    ("NONE", "PETITION_SUBMITTED"),
    ("PETITION_SUBMITTED", "INFO_REQUESTED"),
    ("INFO_REQUESTED", "PETITION_SUBMITTED"),
    ("PETITION_SUBMITTED", "RELIEF_GRANTED"),
    ("PETITION_SUBMITTED", "PETITION_DENIED"),
    ("INFO_REQUESTED", "PETITION_WITHDRAWN"),
}


@bp.post("/participants/<participant_id>/license-relief")
def drive_license_relief(participant_id):
    require_roles(["CaseManager", "ProgramDirector"])
    payload = body()
    to_status = req_enum(payload, "to_status", LICENSE_RELIEF_STATES)
    occupation_code = opt_str(payload, "occupation_code")
    opt_str(payload, "note")

    participant = resolve("participants", db.participants, participant_id)
    _require_not_exited(participant)

    current = participant["license_relief_status"]
    if (current, to_status) not in LICENSE_EDGES:
        fail("ERR_PARTICIPANT_INVALID_STATE",
             "That licence-relief transition is not declared")

    if current == "NONE" and to_status == "PETITION_SUBMITTED":
        if occupation_code is None:
            fail("ERR_VALIDATION",
                 "occupation_code is required to open a petition")
        participant["license_relief_occupation_code"] = occupation_code
    elif current == "INFO_REQUESTED" and to_status == "PETITION_SUBMITTED":
        if int(participant["petition_rounds_used"]) >= PETITION_MAX_ROUNDS:
            fail("ERR_PETITION_ROUNDS_EXHAUSTED",
                 "No petition rounds remain")
        participant["petition_rounds_used"] = int(
            participant["petition_rounds_used"]) + 1

    participant["license_relief_status"] = to_status
    recompute_posture(participant)
    touch(participant)
    return ok(public(participant))


@bp.post("/participants/<participant_id>/exit")
def exit_participant(participant_id):
    require_roles(["ProgramDirector"])
    payload = body()
    exit_reason = req_enum(payload, "exit_reason", EXIT_REASONS)
    req_date(payload, "exit_date")

    participant = resolve("participants", db.participants, participant_id)
    if participant["stage"] == "EXITED":
        fail("ERR_PARTICIPANT_INVALID_STATE", "The participant is already exited")
    if active_placement_count_of_participant(participant_id) > 0:
        fail("ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT",
             "Separate every active placement before closing the case")
    if participant["stage"] not in ("PRE_RELEASE", "RELEASE_READY",
                                    "POST_RELEASE", "RETENTION"):
        fail("ERR_PARTICIPANT_INVALID_STATE",
             "Exit is not legal from the current stage")

    participant["stage"] = "EXITED"
    participant["exit_reason"] = exit_reason
    participant["exit_date"] = payload["exit_date"]
    recompute_posture(participant)
    touch(participant)
    apply_exit_cascade(participant)
    return ok(public(participant))


@bp.get("/participants/<participant_id>/readiness-summary")
def readiness_summary(participant_id):
    require_roles(READ_ROLES)
    participant = resolve("participants", db.participants, participant_id)
    return ok({
        "participant_id": participant["id"],
        "stage": participant["stage"],
        "doc_completeness_pct": participant["doc_completeness_pct"],
        "required_document_count": len(
            participant["required_document_types"] or []),
        "verified_document_count": len(
            participant["verified_document_types"] or []),
        "barrier_score": participant["barrier_score"],
        "barrier_tier": participant["barrier_tier"],
        "release_plan_status": participant["release_plan_status"],
        "readiness_met": readiness_met(participant),
    })

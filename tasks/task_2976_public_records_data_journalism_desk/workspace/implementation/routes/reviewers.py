"""ExpertReviewer and ReviewAssignment endpoints (PRD section 3.8)."""
from flask import Blueprint

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_EXPERT_REVIEWER, ROLE_MANAGING_EDITOR,
                        authenticate)
from services import investigation as inv_service

bp = Blueprint("reviewers", __name__)

EXPERTISE_CODES = ("HOUSING", "PUBLIC_HEALTH", "POLICING", "PROCUREMENT", "STATISTICS")
VERDICTS = ("CONFIRMED", "DISPUTED")
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 2


@bp.post("/expert-reviewers")
def create_reviewer():
    authenticate([ROLE_MANAGING_EDITOR])
    payload = v.body()
    name = v.field_string(payload, "name", min_len=1, max_len=120, non_blank=True)
    affiliation = v.field_string(payload, "affiliation", min_len=1, max_len=160, non_blank=True)
    expertise_code = v.field_enum(payload, "expertise_code", EXPERTISE_CODES)
    max_concurrent_assignments = v.field_int(
        payload, "max_concurrent_assignments", minimum=1, maximum=10,
        optional=True, default=DEFAULT_MAX_CONCURRENT_ASSIGNMENTS)
    if max_concurrent_assignments is None:
        max_concurrent_assignments = DEFAULT_MAX_CONCURRENT_ASSIGNMENTS
    conflict_ids = v.field_id_list(payload, "conflict_of_interest_agency_ids",
                                   optional=True, default=[])
    # Rung 6 -- every element must reference an existing agency
    for agency_id in conflict_ids:
        db.get_agency(agency_id)
    reviewer = db.insert("expert_reviewers", {
        "name": name,
        "affiliation": affiliation,
        "expertise_code": expertise_code,
        "max_concurrent_assignments": max_concurrent_assignments,
        "conflict_of_interest_agency_ids": conflict_ids,
        "active_assignment_count": 0,
    })
    return response.created_response(db.serialize(reviewer))


@bp.get("/expert-reviewers/<reviewer_id>")
def get_reviewer(reviewer_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_reviewer(reviewer_id)))


def _conflicted_agency_ids(investigation_id):
    """Every agency the investigation's datasets were acquired from."""
    agency_ids = []
    for dataset in db.datasets_of_investigation(investigation_id):
        request_row = db.find("records_requests", dataset["request_id"])
        if request_row is None:
            continue
        if request_row["agency_id"] not in agency_ids:
            agency_ids.append(request_row["agency_id"])
    return agency_ids


def _overlapping_assigned_count(reviewer_id, window_start, window_end):
    """Closed-interval overlap against the reviewer's ASSIGNED assignments."""
    count = 0
    for row in db.assignments_of_reviewer(reviewer_id):
        if row["status"] != "ASSIGNED":
            continue
        other_start = clock.instant_of(row["window_start"])
        other_end = clock.instant_of(row["window_end"])
        if other_start is None or other_end is None:
            continue
        if window_start <= other_end and other_start <= window_end:
            count += 1
    return count


@bp.post("/review-assignments")
def create_assignment():
    authenticate([ROLE_MANAGING_EDITOR])
    payload = v.body()
    reviewer_id = v.field_string(payload, "reviewer_id", min_len=1, non_blank=True)
    finding_id = v.field_string(payload, "finding_id", min_len=1, non_blank=True)
    window_start = v.field_instant(payload, "window_start")
    window_end = v.field_instant(payload, "window_end")
    v.require_end_after_start(window_start, window_end, "window_start", "window_end")
    # Rung 6 -- references in declared order
    reviewer = db.get_reviewer(reviewer_id)
    finding = db.get_finding(finding_id)
    # Rung 21 -- conflict of interest is checked first
    conflicts = reviewer["conflict_of_interest_agency_ids"] or []
    if conflicts:
        for agency_id in _conflicted_agency_ids(finding["investigation_id"]):
            if agency_id in conflicts:
                raise ApiError(
                    "ERR_REVIEWER_CONFLICT_OF_INTEREST",
                    "The reviewer is conflicted with an agency that sourced this "
                    "investigation's data.",
                )
    # Rung 28 -- aggregate window capacity
    overlapping = _overlapping_assigned_count(reviewer_id, window_start, window_end)
    if overlapping + 1 > reviewer["max_concurrent_assignments"]:
        raise ApiError(
            "ERR_REVIEWER_CAPACITY_EXCEEDED",
            "The reviewer already holds %d overlapping assignments against a capacity of %d."
            % (overlapping, reviewer["max_concurrent_assignments"]),
        )
    assignment = db.insert("review_assignments", {
        "reviewer_id": reviewer_id,
        "finding_id": finding_id,
        "window_start": clock.iso(window_start),
        "window_end": clock.iso(window_end),
        "status": "ASSIGNED",
        "verdict": None,
        "rationale": None,
    })
    reviewer["active_assignment_count"] = reviewer["active_assignment_count"] + 1
    db.touch(reviewer)
    return response.created_response(db.serialize(assignment))


@bp.get("/review-assignments/<assignment_id>")
def get_assignment(assignment_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_assignment(assignment_id)))


@bp.get("/review-assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("review_assignments"),
                           ["reviewer_id", "finding_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/review-assignments/<assignment_id>/verdict")
def submit_verdict(assignment_id):
    user_id, _ = authenticate([ROLE_EXPERT_REVIEWER])
    assignment = db.get_assignment(assignment_id)
    payload = v.body()
    verdict = v.field_enum(payload, "verdict", VERDICTS)
    rationale = v.field_text(payload, "rationale")
    # Rung 7 -- ownership, ahead of any state check
    if user_id != assignment["reviewer_id"]:
        raise ApiError("ERR_ASSIGNMENT_NOT_OWNED",
                       "Only the assigned expert reviewer may return this verdict.")
    finding = db.find("findings", assignment["finding_id"])
    # Rung 10 -- both state conditions answer with the finding-state code
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_FINDING_STATE",
                       "A verdict is only declared against an assignment in ASSIGNED.")
    if finding is None or finding["verification_status"] != "DOC_MATCHED":
        raise ApiError("ERR_INVALID_FINDING_STATE",
                       "The linked finding must be DOC_MATCHED before an expert verdict.")
    assignment["status"] = "COMPLETED"
    assignment["verdict"] = verdict
    assignment["rationale"] = rationale
    db.touch(assignment)
    reviewer = db.find("expert_reviewers", assignment["reviewer_id"])
    if reviewer is not None:
        reviewer["active_assignment_count"] = reviewer["active_assignment_count"] - 1
        db.touch(reviewer)
    if verdict == "CONFIRMED":
        finding["verification_status"] = "SME_CONFIRMED"
        finding["sme_verdict_rationale"] = rationale
        to_bucket = "SME_CONFIRMED"
    else:
        finding["verification_status"] = "SME_DISPUTED"
        to_bucket = "SME_DISPUTED"
    db.touch(finding)
    investigation = db.find("investigations", finding["investigation_id"])
    if investigation is not None:
        inv_service.move_bucket(investigation, "DOC_MATCHED", to_bucket)
        inv_service.recompute_readiness(investigation)
        db.touch(investigation)
    return response.object_response(db.serialize(assignment))

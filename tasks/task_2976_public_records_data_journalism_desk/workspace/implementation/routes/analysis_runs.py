"""AnalysisRun endpoints (PRD section 3.7)."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_DATA_REPORTER, ROLE_PEER_REVIEWER,
                        authenticate)
from services import calculations
from services import investigation as inv_service

bp = Blueprint("analysis_runs", __name__)

REVIEW_DECISIONS = ("APPROVED", "CHANGES_REQUESTED")
REVIEWABLE_STATUSES = ("PENDING_REVIEW", "CHANGES_REQUESTED")
ALLOCATABLE_INVESTIGATION_STATUSES = ("ANALYSIS", "FINDINGS_LOCKED")
RUN_FORBIDDEN_INVESTIGATION_STATUSES = ("PUBLISHED", "HOLD_LEGAL_REVIEW")

COMMIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
CONTAINER_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


def _invalid_investigation_state(investigation):
    return ApiError(
        "ERR_INVALID_INVESTIGATION_STATE",
        "The operation is not declared from investigation status %s." % investigation["status"],
    )


@bp.post("/analysis-runs")
def create_run():
    user_id, _ = authenticate([ROLE_DATA_REPORTER])
    payload = v.body()
    investigation_id = v.field_string(payload, "investigation_id", min_len=1, non_blank=True)
    code_repo_ref = v.field_string(payload, "code_repo_ref", min_len=1, max_len=200,
                                   non_blank=True)
    code_commit_sha = v.field_string(
        payload, "code_commit_sha", min_len=40, max_len=40, non_blank=True,
        pattern=COMMIT_SHA_PATTERN,
        pattern_desc="must be exactly 40 lowercase hexadecimal characters")
    container_digest = v.field_string(
        payload, "container_digest", min_len=1, non_blank=True,
        pattern=CONTAINER_DIGEST_PATTERN,
        pattern_desc="must be 'sha256:' followed by exactly 64 lowercase hexadecimal characters")
    compute_cost_cents = v.field_int(payload, "compute_cost_cents", minimum=0,
                                     maximum=100000000)
    labor_hours = v.field_number(payload, "labor_hours", minimum=0.0, maximum=10000.0)
    expected_investigation_version = v.field_int(payload, "expected_investigation_version")
    # Rung 6
    investigation = db.get_investigation(investigation_id)
    # Rung 9 -- optimistic concurrency on the investigation
    if expected_investigation_version != investigation["version"]:
        raise ApiError(
            "ERR_STALE_INVESTIGATION_VERSION",
            "expected_investigation_version %s does not match the investigation's current "
            "version %s." % (expected_investigation_version, investigation["version"]),
        )
    # Rung 10
    if investigation["status"] in RUN_FORBIDDEN_INVESTIGATION_STATUSES:
        raise _invalid_investigation_state(investigation)
    labor_cost_cents = calculations.labor_cost_cents(labor_hours)
    run_sequence = len(db.runs_of_investigation(investigation_id)) + 1
    run = db.insert("analysis_runs", {
        "investigation_id": investigation_id,
        "run_sequence": run_sequence,
        "code_repo_ref": code_repo_ref,
        "code_commit_sha": code_commit_sha,
        "container_digest": container_digest,
        "authored_by_user_id": user_id,
        "compute_cost_cents": compute_cost_cents,
        "labor_hours": labor_hours,
        "labor_cost_cents": labor_cost_cents,
        "total_cost_cents": compute_cost_cents + labor_cost_cents,
        "allocated_total_cents": 0,
        "code_review_status": "PENDING_REVIEW",
        "cost_allocation_status": "NOT_ALLOCATED",
        "review_cycle_count": 0,
        "peer_review_note": None,
        "reviewed_by_user_id": None,
    })
    if investigation["status"] == "DRAFTING":
        investigation["status"] = "ANALYSIS"
    inv_service.recompute_readiness(investigation)
    db.touch(investigation)
    return response.created_response(db.serialize(run))


@bp.get("/analysis-runs/<run_id>")
def get_run(run_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_run(run_id)))


@bp.get("/analysis-runs")
def list_runs():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("analysis_runs"),
                           ["investigation_id", "code_review_status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/analysis-runs/<run_id>/cost-allocation")
def allocate_cost(run_id):
    authenticate([ROLE_DATA_REPORTER])
    run = db.get_run(run_id)
    investigation = db.find("investigations", run["investigation_id"])
    # Rung 10 -- the run's investigation must be in ANALYSIS or FINDINGS_LOCKED
    if investigation is None or investigation["status"] not in ALLOCATABLE_INVESTIGATION_STATUSES:
        raise _invalid_investigation_state(investigation or {"status": "UNKNOWN"})
    # Rung 32 -- at least one CLEAN_LOCKED dataset, or nothing is written
    allocation = calculations.compute_cost_allocation(run, investigation["id"])
    for dataset, share in zip(allocation["allocable"], allocation["shares"]):
        dataset["allocated_cost_cents"] = share
        db.touch(dataset)
    run["labor_cost_cents"] = allocation["labor_cost_cents"]
    run["total_cost_cents"] = allocation["total_cost_cents"]
    run["allocated_total_cents"] = allocation["total_cost_cents"]
    run["cost_allocation_status"] = "ALLOCATED"
    db.touch(run)
    inv_service.recompute_readiness(investigation)
    db.touch(investigation)
    return response.object_response(db.serialize(run))


@bp.post("/analysis-runs/<run_id>/peer-review")
def peer_review(run_id):
    user_id, _ = authenticate([ROLE_PEER_REVIEWER])
    run = db.get_run(run_id)
    payload = v.body()
    decision = v.field_enum(payload, "decision", REVIEW_DECISIONS)
    peer_review_note = v.field_text(payload, "peer_review_note")
    # Rung 8 -- segregation of duties, ahead of any state check
    if user_id == run["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The author of a run may never peer-review it.")
    # Rung 10
    if run["code_review_status"] not in REVIEWABLE_STATUSES:
        raise ApiError("ERR_INVALID_RUN_STATE",
                       "A peer review is not declared from code_review_status %s."
                       % run["code_review_status"])
    run["code_review_status"] = decision
    run["review_cycle_count"] = run["review_cycle_count"] + 1
    run["peer_review_note"] = peer_review_note
    run["reviewed_by_user_id"] = user_id
    db.touch(run)
    investigation = db.find("investigations", run["investigation_id"])
    if investigation is not None:
        inv_service.recompute_readiness(investigation)
        db.touch(investigation)
    return response.object_response(db.serialize(run))

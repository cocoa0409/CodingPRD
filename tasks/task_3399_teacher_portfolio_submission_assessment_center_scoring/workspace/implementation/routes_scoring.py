"""Scoring assignment endpoints (PRD 3.6): create (live or calibration),
read, list, submit-score with double-blind resolution and adjudication."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import constants as C
import domain
import errors as E
import serializers as ser
from response import ok, ok_list
from store import DB, new_id, stamp_new, touch, now
from validation import (auth_headers, require_role, body, req_field,
                        pagination_params, paginate, validate_score_value)

bp = Blueprint("scoring", __name__)

_READ_STATES = ("ASSIGNED", "SCORE_SUBMITTED", "FINALIZED")


def _get_assignment_or_404(assignment_id):
    asg = DB.assignments.get(assignment_id)
    if asg is None:
        E.fail(E.ERR_ASSIGNMENT_NOT_FOUND, 404,
               "Assignment not found: %s" % assignment_id)
    return asg


def _live_reads_of(submission_id):
    return [x for x in DB.assignments.values()
            if x.get("submission_id") == submission_id
            and x["status"] in _READ_STATES]


@bp.post("/assignments")
def create_assignment():
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN])
    data = body()
    submission_id = data.get("submission_id")
    benchmark_id = data.get("benchmark_id")
    assessor_id = data.get("assessor_id")
    # Existence gate for every body-supplied id (left of the ambiguity gate).
    sub = None
    bench = None
    assessor = None
    if submission_id is not None:
        sub = DB.submissions.get(submission_id)
        if sub is None:
            E.fail(E.ERR_SUBMISSION_NOT_FOUND, 404,
                   "Submission not found: %s" % submission_id)
    if benchmark_id is not None:
        bench = DB.benchmarks.get(benchmark_id)
        if bench is None:
            E.fail(E.ERR_BENCHMARK_NOT_FOUND, 404,
                   "Benchmark not found: %s" % benchmark_id)
    if assessor_id is not None:
        assessor = DB.assessors.get(assessor_id)
        if assessor is None:
            E.fail(E.ERR_ASSESSOR_NOT_FOUND, 404,
                   "Assessor not found: %s" % assessor_id)
    # Pinned order (PRD 2.8): target ambiguity before conflict-of-interest.
    if (submission_id is None) == (benchmark_id is None):
        E.fail(E.ERR_ASSIGNMENT_TARGET_AMBIGUOUS, 422,
               "Exactly one of submission_id / benchmark_id must be non-null")
    if sub is not None:
        if sub["status"] not in ("SCORING", "ADJUDICATION_REQUIRED"):
            E.fail(E.ERR_SUBMISSION_NOT_SCORABLE, 409,
                   "Live target submission must be SCORING or "
                   "ADJUDICATION_REQUIRED")
    if assessor is None and bench is not None:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "assessor_id is required for a calibration target")
    if assessor is not None:
        if sub is not None and assessor["status"] != "ACTIVE":
            E.fail(E.ERR_ASSESSOR_NOT_SCORING_ELIGIBLE, 409,
                   "Live scoring requires an ACTIVE assessor")
        if bench is not None and assessor["status"] != "CALIBRATING":
            E.fail(E.ERR_ASSESSOR_NOT_SCORING_ELIGIBLE, 409,
                   "Calibration reads require a CALIBRATING assessor")
    if sub is not None:
        candidate = DB.candidates[sub["candidate_id"]]
        if assessor is None:
            assessor = domain.choose_assessor(sub)
        if assessor["home_district_code"] == candidate["district_code"]:
            E.fail(E.ERR_CONFLICT_OF_INTEREST, 403,
                   "Assessor may not score a candidate from their own district")
        prior_readers = {x["assessor_id"] for x in _live_reads_of(sub["id"])}
        if assessor["id"] in prior_readers:
            E.fail(E.ERR_READ_SEGREGATION_VIOLATION, 403,
                   "A later read may not go to an assessor who already read "
                   "this submission")
        read_number = len(_live_reads_of(sub["id"])) + 1
    else:
        read_number = sum(1 for x in DB.assignments.values()
                          if x["assessor_id"] == assessor["id"]
                          and x.get("benchmark_id") is not None
                          and x["status"] != "REASSIGNED") + 1
    assignment = {
        "id": new_id(),
        "assessor_id": assessor["id"],
        "submission_id": submission_id,
        "benchmark_id": benchmark_id,
        "read_number": read_number,
        "status": "ASSIGNED",
        "score": None,
        "score_submitted_at": None,
        "is_within_tolerance": None,
    }
    stamp_new(assignment)
    DB.assignments[assignment["id"]] = assignment
    return ok(ser.assignment(assignment), 201)


@bp.get("/assignments/<assignment_id>")
def get_assignment(assignment_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_ASSESSOR, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN])
    asg = _get_assignment_or_404(assignment_id)
    if role == C.ROLE_ASSESSOR and asg["assessor_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Assessors may read only their own assignments")
    return ok(ser.assignment(asg))


@bp.get("/assignments")
def list_assignments():
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN, C.ROLE_BOARD_ADMIN])
    limit, offset = pagination_params()
    items = list(DB.assignments.values())
    assessor_id = request.args.get("assessor_id")
    if assessor_id is not None:
        items = [x for x in items if x["assessor_id"] == assessor_id]
    submission_id = request.args.get("submission_id")
    if submission_id is not None:
        items = [x for x in items if x.get("submission_id") == submission_id]
    benchmark_id = request.args.get("benchmark_id")
    if benchmark_id is not None:
        items = [x for x in items if x.get("benchmark_id") == benchmark_id]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.assignment(x) for x in page], limit, offset, total)


def _finalize_calibration(asg, assessor):
    bench = DB.benchmarks[asg["benchmark_id"]]
    # Boundary is inclusive: |score - known_score| == tolerance passes.
    within = abs(asg["score"] - Decimal(str(bench["known_score"]))) \
        <= Decimal(str(bench["tolerance"]))
    asg["is_within_tolerance"] = within
    asg["status"] = "FINALIZED"
    if within:
        assessor["calibration_passes"] += 1
    else:
        assessor["calibration_failures"] += 1
    if assessor["status"] == "CALIBRATING":
        if assessor["calibration_passes"] >= C.REQUIRED_CALIBRATION_PASSES:
            assessor["status"] = "CALIBRATED"
            assessor["calibrated_at"] = now()
        elif assessor["calibration_failures"] >= C.MAX_CALIBRATION_FAILURES:
            domain.suspend_assessor(assessor)
            return
    touch(assessor)


def _resolve_live_reads(sub, just_submitted):
    """Double-blind resolution (PRD 3.6): agreement at |d| <= 0.50 scores the
    attempt with the rounded mean; divergence moves to ADJUDICATION_REQUIRED;
    the adjudication read scores the attempt outright."""
    if sub["status"] == "ADJUDICATION_REQUIRED":
        # The just-submitted read is the adjudication read (read_number 3).
        sub["final_score"] = just_submitted["score"]
        sub["status"] = "SCORED"
        touch(sub)
        finalized = []
        for read in _live_reads_of(sub["id"]):
            read["status"] = "FINALIZED"
            touch(read)
            finalized.append(read)
        for read in finalized:
            domain.irr_check_after_finalization(read["assessor_id"])
        domain.on_submission_scored(sub)
        return
    if sub["status"] != "SCORING":
        return
    submitted = [x for x in _live_reads_of(sub["id"])
                 if x["status"] == "SCORE_SUBMITTED"]
    if len(submitted) < 2:
        return
    submitted.sort(key=lambda x: x["read_number"])
    read1, read2 = submitted[0], submitted[1]
    divergence = abs(read1["score"] - read2["score"])
    if divergence <= C.DIVERGENCE_TOLERANCE:
        mean = (read1["score"] + read2["score"]) / Decimal("2")
        sub["final_score"] = mean.quantize(C.SCORE_QUANT, rounding=ROUND_HALF_UP)
        sub["status"] = "SCORED"
        touch(sub)
        for read in (read1, read2):
            read["status"] = "FINALIZED"
            touch(read)
        for read in (read1, read2):
            domain.irr_check_after_finalization(read["assessor_id"])
        domain.on_submission_scored(sub)
    else:
        sub["status"] = "ADJUDICATION_REQUIRED"
        touch(sub)


@bp.post("/assignments/<assignment_id>/submit-score")
def submit_score(assignment_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_ASSESSOR])
    asg = _get_assignment_or_404(assignment_id)
    if asg["assessor_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "An assessor may submit a score only for their own assignment")
    if asg["status"] != "ASSIGNED":
        E.fail(E.ERR_ASSIGNMENT_NOT_SUBMITTABLE, 409,
               "Assignment must be ASSIGNED to submit a score")
    data = body()
    if "score" not in data or data["score"] is None:
        E.fail(E.ERR_INVALID_REQUEST, 400, "score is required")
    asg["score"] = validate_score_value(data["score"])
    asg["score_submitted_at"] = now()
    assessor = DB.assessors[asg["assessor_id"]]
    if asg.get("benchmark_id") is not None:
        _finalize_calibration(asg, assessor)
        touch(asg)
    else:
        asg["status"] = "SCORE_SUBMITTED"
        touch(asg)
        sub = DB.submissions[asg["submission_id"]]
        _resolve_live_reads(sub, asg)
    return ok(ser.assignment(asg))

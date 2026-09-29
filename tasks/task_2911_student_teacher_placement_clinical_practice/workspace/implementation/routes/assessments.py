"""Performance assessment endpoints (PRD 3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import flows
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("assessments", __name__)

READERS = ["AssessmentScorer", "ProgramAdmin", "PlacementCoordinator",
           "CandidateUser"]
RUBRIC_FIELDS = ("task_planning", "task_instruction", "task_assessment",
                 "task_professionalism")


def _payload_invalid(message):
    return ApiError("ERR_SCORE_PAYLOAD_INVALID", message)


@bp.post("/epp/performance-assessments")
@endpoint(["AssessmentScorer", "ProgramAdmin"])
def open_assessment():
    body = shapes.body_of(request)
    placement_id = shapes.req_str(body, "placement_id", 1, None)
    opens_at = shapes.req_instant(body, "window_opens_at")
    closes_at = shapes.req_instant(body, "window_closes_at")

    placement = store.get_placement(placement_id)

    # Rung 8 -- the interval itself.
    if not closes_at > opens_at:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_closes_at must be strictly later than "
                       "window_opens_at.")

    # Rung 11 -- one assessment per placement, ever.
    if store.assessment_of_placement(placement["id"]) is not None:
        raise ApiError("ERR_ASSESSMENT_ALREADY_EXISTS",
                       "The placement already has a performance assessment.")

    # Rung 15 -- scheduling clinical work needs an ACTIVE agreement.
    agreement = store.AGREEMENTS.get(placement["agreement_id"])
    if agreement is not None:
        derive.expire_agreement(agreement)
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                           "The placement's backing agreement is not ACTIVE.")

    row = store.new_row({
        "placement_id": placement["id"],
        "window_opens_at": opens_at,
        "window_closes_at": closes_at,
        "status": "OPEN",
        "attempt_no": 0,
        "artifact_reference": None,
        "submitted_at": None,
        "task_planning": None,
        "task_instruction": None,
        "task_assessment": None,
        "task_professionalism": None,
        "total_score": 0,
        "scored_by_user_id": None,
        "scored_at": None,
        "returned_feedback": None,
    })
    store.ASSESSMENTS[row["id"]] = row
    return envelope.created(views.dump(row, views.ASSESSMENT))


@bp.get("/epp/performance-assessments/<assessment_id>")
@endpoint(READERS)
def read_assessment(assessment_id):
    row = store.get_assessment(assessment_id)
    return envelope.ok(views.dump(row, views.ASSESSMENT))


@bp.get("/epp/performance-assessments")
@endpoint(["AssessmentScorer", "ProgramAdmin", "PlacementCoordinator"])
def list_assessments():
    page, page_size = shapes.pagination(request.args)
    placement_id = request.args.get("placement_id") or None
    status = shapes.query_enum(request.args, "status",
                              shapes.ASSESSMENT_STATUSES)
    rows = []
    for row in store.all_of(store.ASSESSMENTS):
        if placement_id is not None and row["placement_id"] != placement_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.ASSESSMENT),
                            page, page_size, total)


@bp.post("/epp/performance-assessments/<assessment_id>/submit")
@endpoint(["CandidateUser"])
def submit_assessment(assessment_id):
    row = store.get_assessment(assessment_id)
    placement = store.PLACEMENTS.get(row["placement_id"])

    # Rung 4 -- only the placement's own candidate may submit.
    if placement is not None:
        auth.require_owner(placement["candidate_id"])

    body = shapes.body_of(request)
    artifact_reference = shapes.req_str(body, "artifact_reference", 1, None)

    # Rung 17 -- the owning placement must still be ACTIVE.
    if placement is not None and placement["placement_status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "The owning placement is not ACTIVE.")

    # Rung 21 -- the assessment must accept a portfolio.
    if row["status"] not in ("OPEN", "RETURNED"):
        raise ApiError("ERR_ASSESSMENT_STATE_INVALID",
                       "Only an OPEN or RETURNED assessment may be submitted.")

    # Rung 34 -- the closed-closed submission window, grace included.
    if not (row["window_opens_at"] <= clock.now() <= row["window_closes_at"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                       "The submission window is not open.")

    # Rung 35 -- the observation compliance floor.
    if placement is not None:
        ratio = derive.derive_placement_observations(placement)
        if ratio < Decimal("0.5"):
            raise ApiError("ERR_OBSERVATION_COMPLIANCE_LOW",
                           "The placement's observation compliance ratio is "
                           "below 0.5.")

    row["status"] = "SUBMITTED"
    row["attempt_no"] = int(row["attempt_no"]) + 1
    row["artifact_reference"] = artifact_reference
    row["submitted_at"] = clock.now()
    store.touch(row)
    return envelope.ok(views.dump(row, views.ASSESSMENT))


def _return_portfolio(row, feedback):
    """The shared RETURN terms (PRD 3.8): no scores, grace extension."""
    row["status"] = "RETURNED"
    row["returned_feedback"] = feedback
    row["submitted_at"] = None
    row["window_closes_at"] = row["window_closes_at"] + timedelta(
        days=calc.RESUBMISSION_GRACE_DAYS)
    store.touch(row)


@bp.post("/epp/performance-assessments/<assessment_id>/score")
@endpoint(["AssessmentScorer"])
def score_assessment(assessment_id):
    row = store.get_assessment(assessment_id)
    body = shapes.body_of(request)
    decision = shapes.req_enum(body, "decision", ("SCORE", "RETURN"))
    if shapes.present(body, "returned_feedback"):
        shapes.req_str(body, "returned_feedback", 1, None)
    for name in RUBRIC_FIELDS:
        if name in body and body[name] is not None:
            if isinstance(body[name], bool) or not isinstance(
                    body[name], (int, float)):
                raise shapes.bad("Field '%s' must be a JSON number." % name)

    # Rung 21 -- only a SUBMITTED portfolio may be disposed of.
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_ASSESSMENT_STATE_INVALID",
                       "Only a SUBMITTED assessment may be scored.")

    # A candidate may never score their own assessment (PRD 2.11).
    placement = store.PLACEMENTS.get(row["placement_id"])
    if placement is not None and placement["candidate_id"] == auth.user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A candidate may never score their own assessment.")

    attempt_no = int(row["attempt_no"])
    carries_scores = any(name in body and body[name] is not None
                         for name in RUBRIC_FIELDS)

    if decision == "RETURN":
        # Rung 38 -- a final attempt must be failed, never returned.
        if attempt_no >= calc.MAX_ASSESSMENT_ATTEMPTS:
            raise ApiError("ERR_ASSESSMENT_ATTEMPTS_EXHAUSTED",
                           "The final attempt must be scored, not returned.")
        # Rung 39 -- a return carries feedback and no scores.
        if carries_scores:
            raise _payload_invalid(
                "A RETURN decision may not carry rubric dimension scores.")
        if not shapes.present(body, "returned_feedback"):
            raise _payload_invalid(
                "A RETURN decision requires returned_feedback.")
        _return_portfolio(row, body["returned_feedback"])
        return envelope.ok(views.dump(row, views.ASSESSMENT))

    # Rung 39 -- a scoring decision carries all four dimensions, on the step.
    scores = {}
    for name in RUBRIC_FIELDS:
        if name not in body or body[name] is None:
            raise _payload_invalid(
                "A SCORE decision requires '%s'." % name)
        if not shapes.is_step_number(body[name], "1.0", "5.0", "0.5"):
            raise _payload_invalid(
                "Field '%s' must be a multiple of 0.5 inside 1.0 through 5.0."
                % name)
        scores[name] = Decimal(str(body[name]))

    total = calc.assessment_total_score(scores)
    if total >= calc.ASSESSMENT_CUT_SCORE:
        for name in RUBRIC_FIELDS:
            row[name] = scores[name]
        row["total_score"] = total
        row["scored_by_user_id"] = auth.user_id()
        row["scored_at"] = clock.now()
        row["status"] = "PASSED"
        store.touch(row)
        return envelope.ok(views.dump(row, views.ASSESSMENT))

    if attempt_no < calc.MAX_ASSESSMENT_ATTEMPTS:
        # A sub-cut score before the final attempt returns the portfolio on
        # exactly the terms of an explicit return.
        _return_portfolio(row, body.get("returned_feedback"))
        return envelope.ok(views.dump(row, views.ASSESSMENT))

    for name in RUBRIC_FIELDS:
        row[name] = scores[name]
    row["total_score"] = total
    row["scored_by_user_id"] = auth.user_id()
    row["scored_at"] = clock.now()
    row["status"] = "FAILED"
    store.touch(row)

    # The four-level failure cascade (PRD 3.8).
    if placement is not None and placement["placement_status"] == "ACTIVE":
        flows.enter_removal_pending(placement, "ASSESSMENT_FAILURE", "system",
                                    None, None)
    return envelope.ok(views.dump(row, views.ASSESSMENT))

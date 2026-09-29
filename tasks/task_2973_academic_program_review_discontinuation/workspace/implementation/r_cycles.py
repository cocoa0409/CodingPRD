"""Review cycles: retrieval, the self-study document, the program response
and decision-record proposal."""

from decimal import Decimal

from flask import Blueprint

import derive
import envelope
import filters
import serial
import valid
from errors import ApiError
from guards import (CHAIR, COORD, PROVOST, REGISTRAR, REVIEWER, HR, begin,
                    program_of_cycle)
from store import by_created, db, new_row, now, touch

bp = Blueprint("cycles", __name__)

OUTCOMES = ("CONTINUE", "IMPROVEMENT_PLAN", "CONSOLIDATION", "DISCONTINUATION")
CONCURRENCES = ("CONCUR", "PARTIAL_CONCUR", "DISPUTE")

BAND_SUPPORT = {
    "CONTINUE": ("CONTINUE_ELIGIBLE", "IMPROVEMENT_ELIGIBLE"),
    "IMPROVEMENT_PLAN": ("IMPROVEMENT_ELIGIBLE", "NONVIABLE"),
    "CONSOLIDATION": ("NONVIABLE",),
    "DISCONTINUATION": ("NONVIABLE",),
}


@bp.route("/provost/review-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    ctx = begin((COORD, PROVOST, CHAIR, REVIEWER))
    cycle = db.cycles.get(cid)
    ctx.chair_owner(program_of_cycle(cycle))
    ctx.require(cycle, "ERR_CYCLE_NOT_FOUND")
    return envelope.ok(serial.cycle(cycle))


# --------------------------------------------------------------------------
# the cycle's single self-study
# --------------------------------------------------------------------------

@bp.route("/provost/review-cycles/<cid>/self-studies", methods=["POST"])
def create_self_study(cid):
    ctx = begin((CHAIR,))
    cycle = db.cycles.get(cid)
    ctx.chair_owner(program_of_cycle(cycle))
    ctx.require(cycle, "ERR_CYCLE_NOT_FOUND")

    body = ctx.require_object_body()
    narrative = valid.req_str(body, "narrative", 1, 20000)
    sections = valid.code_array(body, "section_codes", 1, 20, allow_empty=True)

    ctx.not_terminal(program_of_cycle(cycle))

    if derive.self_study_of(cid) is not None:
        raise ApiError("ERR_SELF_STUDY_ALREADY_EXISTS")

    row = new_row()
    row.update({
        "cycle_id": cid,
        "narrative": narrative,
        "section_codes": sections,
        "state": "DRAFT",
        "revision_round": 0,
        "submitted_at": None,
        "accepted_at": None,
        "revision_notes": None,
        "attestation_note": None,
    })
    db.self_studies[row["id"]] = row
    return envelope.created(serial.self_study(row))


@bp.route("/provost/review-cycles/<cid>/self-studies", methods=["GET"])
def list_self_studies(cid):
    ctx = begin((COORD, PROVOST, CHAIR, REVIEWER))
    cycle = db.cycles.get(cid)
    ctx.chair_owner(program_of_cycle(cycle))
    ctx.require(cycle, "ERR_CYCLE_NOT_FOUND")
    rows = by_created([s for s in db.self_studies.values()
                       if s["cycle_id"] == cid])
    rows = filters.apply_string(rows, "state", "state")
    return envelope.paginate(rows, serial.self_study)


# --------------------------------------------------------------------------
# the program response and the addendum loop
# --------------------------------------------------------------------------

@bp.route("/provost/review-cycles/<cid>/program-response", methods=["POST"])
def program_response(cid):
    ctx = begin((CHAIR,))
    cycle = db.cycles.get(cid)
    program = program_of_cycle(cycle)
    ctx.chair_owner(program)
    ctx.require(cycle, "ERR_CYCLE_NOT_FOUND")

    body = ctx.require_object_body()
    concurrence = valid.req_enum(body, "response_concurrence", CONCURRENCES)
    response_text = valid.req_str(body, "response_text", 1, 20000)
    disputed = valid.code_array(body, "disputed_finding_codes", 1, 20,
                                allow_empty=True)
    if concurrence == "DISPUTE" and not disputed:
        valid.fail("disputed_finding_codes must be non-empty on a dispute.")

    ctx.not_terminal(program)

    if cycle["state"] != "REPORT_RECEIVED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    if concurrence == "DISPUTE":
        if cycle["addendum_round"] >= 2:
            raise ApiError("ERR_ADDENDUM_LIMIT_REACHED")
        known = set()
        for visit in derive.visits_of(cid):
            for report in derive.reports_of(visit["id"]):
                known.update(report["finding_codes"])
        for code in disputed:
            if code not in known:
                raise ApiError("ERR_UNKNOWN_FINDING_CODE")

    cycle["response_concurrence"] = concurrence
    cycle["response_text"] = response_text
    cycle["disputed_finding_codes"] = disputed
    cycle["response_submitted_at"] = now()
    if concurrence == "DISPUTE":
        cycle["addendum_round"] = cycle["addendum_round"] + 1
        cycle["state"] = "ADDENDUM_REQUESTED"
    else:
        cycle["state"] = "RESPONSE_SUBMITTED"
    touch(cycle)
    return envelope.ok(serial.cycle(cycle))


# --------------------------------------------------------------------------
# decision-record proposal
# --------------------------------------------------------------------------

@bp.route("/provost/review-cycles/<cid>/decision-records", methods=["POST"])
def propose_decision(cid):
    ctx = begin((PROVOST,))
    cycle = db.cycles.get(cid)
    ctx.require(cycle, "ERR_CYCLE_NOT_FOUND")
    program = program_of_cycle(cycle)

    # check 8: body foreign keys
    receiving = None
    if ctx.body is not None and ctx.body.get("receiving_program_id") is not None:
        supplied = ctx.body.get("receiving_program_id")
        receiving = db.programs.get(supplied) if isinstance(supplied, str) else None
        if receiving is None:
            raise ApiError("ERR_PROGRAM_NOT_FOUND")

    body = ctx.require_object_body()
    outcome = valid.req_enum(body, "outcome", OUTCOMES)
    rationale = valid.req_str(body, "rationale", 1, 5000)
    effective_term = valid.req_term_index(body, "effective_term_index")
    expected = valid.req_int(body, "expected_cycle_version")

    target_score = None
    review_term = None
    milestones = []
    if outcome == "IMPROVEMENT_PLAN":
        target_score = valid.req_decimal(body, "improvement_target_score",
                                         Decimal("0.00"), Decimal("100.00"),
                                         places=2)
        review_term = valid.req_term_index(body, "improvement_review_term_index")
        milestones = valid.text_array(body, "improvement_milestones", 1, 200)
    else:
        valid.forbid_present(
            body, "improvement_target_score",
            "improvement_target_score belongs to the improvement branch only.")
        valid.forbid_present(
            body, "improvement_review_term_index",
            "improvement_review_term_index belongs to the improvement branch "
            "only.")

    # check 10: optimistic concurrency on the cycle
    if expected != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")

    # check 11
    ctx.not_terminal(program)

    # check 12
    self_study = derive.self_study_of(cid)
    if cycle["state"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if self_study is None or self_study["state"] != "ACCEPTED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    # check 27: the band must support the outcome
    score, band = derive.composite_score(program)
    if band == "INSUFFICIENT_DATA":
        raise ApiError("ERR_OUTCOME_NOT_SUPPORTED_BY_VIABILITY")
    if outcome in ("CONSOLIDATION", "DISCONTINUATION"):
        if band not in BAND_SUPPORT[outcome] and not program["discontinuation_override"]:
            raise ApiError("ERR_OUTCOME_NOT_SUPPORTED_BY_VIABILITY")
    elif band not in BAND_SUPPORT[outcome]:
        raise ApiError("ERR_OUTCOME_NOT_SUPPORTED_BY_VIABILITY")

    # check 28: branch discipline on receiving_program_id
    if outcome == "CONSOLIDATION":
        if receiving is None:
            raise ApiError("ERR_RECEIVING_PROGRAM_REQUIRED")
    elif receiving is not None:
        raise ApiError("ERR_RECEIVING_PROGRAM_REQUIRED")

    # check 29: the receiving program is eligible
    if receiving is not None:
        if (receiving["id"] == program["id"]
                or receiving["lifecycle_state"] != "ACTIVE"
                or derive.composite_score(receiving)[1] != "CONTINUE_ELIGIBLE"):
            raise ApiError("ERR_RECEIVING_PROGRAM_INELIGIBLE")

    row = new_row()
    row.update({
        "cycle_id": cid,
        "outcome": outcome,
        "rationale": rationale,
        "effective_term_index": effective_term,
        "receiving_program_id": receiving["id"] if receiving is not None else None,
        "improvement_target_score": target_score,
        "improvement_review_term_index": review_term,
        "improvement_milestones": milestones,
        "state": "PROPOSED",
        "improvement_state": "NOT_APPLICABLE",
        "proposed_by_user_id": ctx.user_id,
        "ratified_by_user_id": None,
        "ratification_note": None,
        "ratified_at": None,
        "effectuated_at": None,
        "rescission_reason": None,
        "composite_score_at_proposal": score,
        "viability_band_at_proposal": band,
    })
    db.decisions[row["id"]] = row

    for existing in by_created(derive.decisions_of(cid)):
        if existing["id"] != row["id"] and existing["state"] == "PROPOSED":
            existing["state"] = "WITHDRAWN"
            touch(existing)

    cycle["state"] = "DECISION_PROPOSED"
    touch(cycle)
    return envelope.created(serial.decision(row))

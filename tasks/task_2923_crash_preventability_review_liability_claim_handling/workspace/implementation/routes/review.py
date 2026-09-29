"""The safety review committee: cases, ballots, determinations and appeals."""

from datetime import timedelta

from flask import Blueprint

import calc
import serializers
from auth import require, REVIEW_READ, VOTE_READ
from common import (claim_for_crash, driver_actions, filtered, lookup,
                    paginate, review_case_for_crash, statement_exists)
from envelope import ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, touch

bp = Blueprint("review", __name__)


@bp.post("/review-cases")
def create_case():
    user_id, _role = require("SafetyManager")
    values = read_body([
        f("crash_id", "string", required=True),
        f("committee_name", "string", required=True),
        f("statement_waiver_reason", "string"),
    ])
    crash = lookup("crashes", values["crash_id"])
    if review_case_for_crash(crash["id"]) is not None:
        fail("ERR_REVIEW_CASE_EXISTS",
             "This crash already carries a review case")
    if crash["preventability_status"] != "REPORTED":
        fail("ERR_CRASH_STATE_INVALID",
             "A review case may only be opened on a REPORTED crash")
    waiver = given(values, "statement_waiver_reason")
    if waiver is None and not statement_exists(crash["id"]):
        fail("ERR_DRIVER_STATEMENT_REQUIRED",
             "The crash has no driver statement and no waiver reason was supplied")
    row = base_row()
    row["crash_id"] = crash["id"]
    row["committee_name"] = values["committee_name"]
    row["statement_waiver_reason"] = waiver
    row["status"] = "DRAFT"
    row["determination"] = "PENDING"
    row["decision_basis"] = "NOT_APPLICABLE"
    row["committee_score"] = None
    row["next_vote_sequence"] = 1
    row["appeal_round"] = 0
    row["appeal_grounds"] = None
    row["appeal_grounds_code"] = None
    row["appeal_evidence_item_id"] = None
    row["decided_by_user_id"] = None
    row["decided_at"] = None
    db.review_cases[row["id"]] = row
    crash["preventability_status"] = "UNDER_REVIEW"
    touch(crash)
    return created(serializers.review_case(row))


@bp.get("/review-cases/<entity_id>")
def read_case(entity_id):
    require(*REVIEW_READ)
    return ok(serializers.review_case(lookup("review_cases", entity_id)))


@bp.get("/review-cases")
def list_cases():
    require(*REVIEW_READ)
    criteria = filters({
        "crash_id": None,
        "appeal_evidence_item_id": None,
        "status": calc.REVIEW_STATUSES,
        "determination": calc.DETERMINATIONS,
    })
    return paginate(filtered("review_cases", criteria), serializers.review_case)


@bp.post("/review-cases/<entity_id>/open-deliberation")
def open_deliberation(entity_id):
    require("SafetyManager")
    read_body([])
    case = lookup("review_cases", entity_id)
    if case["status"] != "DRAFT":
        fail("ERR_REVIEW_CASE_STATE_INVALID",
             "Deliberation may only be opened on a DRAFT review case")
    preserved = [item for item in calc.crash_evidence_items(case["crash_id"])
                 if item["preservation_state"] == "PRESERVED"]
    if not preserved:
        fail("ERR_NO_PRESERVED_EVIDENCE",
             "At least one evidence item must be preserved before deliberation")
    case["status"] = "DELIBERATION"
    touch(case)
    return ok(serializers.review_case(case))


# ---------------------------------------------------------------------------
# Ballots
# ---------------------------------------------------------------------------
@bp.post("/review-cases/<entity_id>/votes")
def cast_vote(entity_id):
    user_id, _role = require("CommitteeMember")
    values = read_body([
        f("expected_review_case_version", "int", required=True),
        f("vote", "string", required=True, enum=calc.VOTES),
        f("criterion_scores", "scores", keys=calc.CRITERION_KEYS),
        f("comment", "string"),
    ])
    vote = values["vote"]
    has_scores = present(values, "criterion_scores")
    if vote == "ABSTAIN" and has_scores:
        fail("ERR_INVALID_REQUEST",
             "criterion_scores must be absent on an abstention")
    if vote != "ABSTAIN" and not has_scores:
        fail("ERR_INVALID_REQUEST",
             "criterion_scores is required on a substantive ballot")
    case = lookup("review_cases", entity_id)
    if case["status"] != "DELIBERATION":
        fail("ERR_REVIEW_CASE_STATE_INVALID",
             "Ballots may only be cast on a case in DELIBERATION")
    if values["expected_review_case_version"] != case["version"]:
        fail("ERR_REVIEW_CASE_VERSION_STALE",
             "The review case has advanced since it was read")
    crash = db.crashes[case["crash_id"]]
    for earlier in calc.case_votes(case["id"]):
        if earlier["member_user_id"] == user_id and not earlier["superseded"]:
            earlier["superseded"] = True
    row = base_row(with_version=False)
    row["review_case_id"] = case["id"]
    row["member_user_id"] = user_id
    row["sequence_number"] = case["next_vote_sequence"]
    row["vote"] = vote
    if vote == "ABSTAIN":
        row["criterion_scores"] = None
        row["weighted_member_score"] = None
    else:
        scores = values["criterion_scores"]
        row["criterion_scores"] = scores
        row["weighted_member_score"] = calc.weighted_member_score(
            scores, crash["mechanical_factor"])
    row["superseded"] = False
    row["comment"] = given(values, "comment")
    row["cast_at"] = db.now
    db.committee_votes[row["id"]] = row
    case["next_vote_sequence"] += 1
    touch(case)
    return created(serializers.review_case(case))


@bp.get("/review-cases/<entity_id>/votes")
def list_votes(entity_id):
    require(*VOTE_READ)
    case = lookup("review_cases", entity_id)
    criteria = filters({"vote": calc.VOTES, "superseded": "bool"})
    criteria["review_case_id"] = case["id"]
    ballots = [v for v in db.committee_votes.values()
               if all(v.get(k) == val for k, val in criteria.items())]
    ballots = sorted(ballots, key=lambda v: (v["created_at"], v["_seq"]))
    return paginate(ballots, serializers.committee_vote)


# ---------------------------------------------------------------------------
# Determination
# ---------------------------------------------------------------------------
@bp.post("/review-cases/<entity_id>/decide")
def decide(entity_id):
    user_id, _role = require("SafetyManager")
    read_body([])
    case = lookup("review_cases", entity_id)
    if case["status"] != "DELIBERATION":
        fail("ERR_REVIEW_CASE_STATE_INVALID",
             "A determination may only be recorded from DELIBERATION")
    for ballot in calc.live_votes(case["id"]):
        if ballot["member_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The decider may not be behind a live ballot on this case")
    crash = db.crashes[case["crash_id"]]
    posture = calc.evidence_posture(crash)
    if posture not in ("COMPLETE", "COMPROMISED"):
        fail("ERR_EVIDENCE_POSTURE_INSUFFICIENT",
             "The evidence record is only PARTIAL")
    if len(calc.live_substantive(case["id"])) < calc.COMMITTEE_QUORUM_MIN:
        fail("ERR_QUORUM_NOT_MET",
             "At least %d live non-abstaining ballots are required"
             % calc.COMMITTEE_QUORUM_MIN)
    score = calc.committee_score(case["id"])
    determination, basis = calc.determination_from(case["id"], posture, score)
    final = case["appeal_round"] >= calc.APPEAL_MAX_ROUNDS
    case["status"] = "CLOSED_FINAL" if final else "DECIDED"
    case["determination"] = determination
    case["decision_basis"] = basis
    case["committee_score"] = score
    case["decided_by_user_id"] = user_id
    case["decided_at"] = db.now
    touch(case)
    crash["preventability_status"] = determination
    if final:
        crash["appeals_exhausted"] = True
    touch(crash)
    return ok(serializers.review_case(case))


# ---------------------------------------------------------------------------
# Appeal
# ---------------------------------------------------------------------------
@bp.post("/review-cases/<entity_id>/appeal")
def appeal(entity_id):
    user_id, _role = require("SafetyManager")
    values = read_body([
        f("appeal_grounds", "string", required=True),
        f("appeal_grounds_code", "string", required=True,
          enum=calc.APPEAL_GROUNDS_CODES),
        f("appeal_evidence_item_id", "string"),
    ])
    code = values["appeal_grounds_code"]
    cited = present(values, "appeal_evidence_item_id")
    if code == "NEW_EVIDENCE" and not cited:
        fail("ERR_INVALID_REQUEST",
             "appeal_evidence_item_id is required for a NEW_EVIDENCE appeal")
    if code != "NEW_EVIDENCE" and cited:
        fail("ERR_INVALID_REQUEST",
             "appeal_evidence_item_id must be absent for a %s appeal" % code)
    case = lookup("review_cases", entity_id)
    item = None
    if cited:
        item = lookup("evidence_items", values["appeal_evidence_item_id"])
    if case["status"] != "DECIDED":
        fail("ERR_REVIEW_CASE_STATE_INVALID",
             "Only a DECIDED review case may be appealed")
    crash = db.crashes[case["crash_id"]]
    if crash["appeals_exhausted"] or case["appeal_round"] >= calc.APPEAL_MAX_ROUNDS:
        fail("ERR_APPEALS_EXHAUSTED",
             "This case has already consumed its permitted appeal")
    if case["decided_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The manager who decided the case may not grant its appeal")
    deadline = case["decided_at"] + timedelta(days=calc.APPEAL_WINDOW_DAYS)
    if db.now > deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED",
             "The %d-day appeal window has closed" % calc.APPEAL_WINDOW_DAYS)
    if item is not None:
        if (item["crash_id"] != crash["id"]
                or item["preservation_state"] != "PRESERVED"):
            fail("ERR_APPEAL_EVIDENCE_INVALID",
                 "The cited evidence item must be a PRESERVED item of this crash")
    case["status"] = "DELIBERATION"
    case["appeal_round"] += 1
    case["appeal_grounds"] = values["appeal_grounds"]
    case["appeal_grounds_code"] = code
    case["appeal_evidence_item_id"] = item["id"] if item is not None else None
    case["determination"] = "PENDING"
    case["decision_basis"] = "NOT_APPLICABLE"
    case["committee_score"] = None
    case["decided_by_user_id"] = None
    case["decided_at"] = None
    touch(case)
    crash["preventability_status"] = "UNDER_REVIEW"
    touch(crash)
    driver = db.drivers[crash["driver_id"]]
    for action in driver_actions(driver["id"]):
        if action["crash_id"] != crash["id"]:
            continue
        if action["status"] != "ISSUED":
            continue
        action["status"] = "VOIDED"
        action["retraining_status"] = "NOT_REQUIRED"
        touch(action)
    tier = calc.required_action_tier(driver)
    remaining = [a for a in driver_actions(driver["id"])
                 if a["action_type"] == "SUSPENSION" and a["status"] != "VOIDED"]
    if (calc.TIER_RANK[tier] < calc.TIER_RANK["SUSPENSION"]
            and not remaining
            and driver["status"] == "SUSPENDED_PENDING_ACTION"):
        driver["status"] = "ACTIVE"
    touch(driver)
    return ok(serializers.review_case(case))

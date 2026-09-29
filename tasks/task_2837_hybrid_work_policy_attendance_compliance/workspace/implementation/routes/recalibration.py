"""RecalibrationReview routes: draft, snapshot submit and the adopt/reject decision."""
from decimal import Decimal

from flask import Blueprint

import calc
import db
import guards
import middleware
from errors import fail
from middleware import (ALL_ROLES, COMPLIANCE_AUDITOR, EMPLOYEE,
                        WORKPLACE_PROGRAM_OFFICE)

bp = Blueprint("recalibration", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)


@bp.route("/recalibration-reviews", methods=["POST"])
def create_review():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    payload = middleware.body()
    cycle_id = middleware.req_present(payload, "policy_cycle_id")
    cycle = middleware.must_exist("policy_cycle", cycle_id)

    label = middleware.req_string(payload, "review_label", 1, 40)
    delta = middleware.req_int(payload, "proposed_days_in_office_delta", -2, 2)

    guards.gate_cycle_not_locked(cycle)

    for existing in db.find("recalibration_review", policy_cycle_id=cycle["id"]):
        if existing["review_label"] == label:
            fail("ERR_DUPLICATE_REVIEW_LABEL", "review_label is already in use on this cycle")

    row = db.insert("recalibration_review", {
        "policy_cycle_id": cycle["id"],
        "review_label": label,
        "proposed_days_in_office_delta": delta,
        "state": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "collaboration_index": Decimal("0.00"),
        "meets_collaboration_target": False,
        "total_space_chargeback_cents": 0,
        "equity_variance_pct": Decimal("0.00"),
        "equity_flag": False,
        "qualifying_band_count": 0,
        "decision_reason": None,
    })
    return guards.single("recalibration_review", row, 201)


@bp.route("/recalibration-reviews/<review_id>/submit", methods=["POST"])
def submit_review(review_id):
    actor = middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    review = middleware.must_exist("recalibration_review", review_id)
    cycle = db.get("policy_cycle", review["policy_cycle_id"])

    guards.gate_cycle_not_locked(cycle)
    if review["state"] != "DRAFT":
        fail("ERR_REVIEW_NOT_DRAFT", "recalibration review is not DRAFT")
    if cycle["posture"] != "RECALIBRATING":
        fail("ERR_CYCLE_NOT_RECALIBRATING", "policy cycle posture is not RECALIBRATING")

    index = calc.collaboration_index(cycle)
    qualifying, variance = calc.equity_variance(cycle)
    db.apply_changes(review, {
        "state": "SUBMITTED",
        "submitted_by_user_id": actor.user_id,
        "collaboration_index": index,
        "meets_collaboration_target": index >= cycle["collaboration_target_score"],
        "total_space_chargeback_cents": calc.cycle_space_chargeback_cents(cycle),
        "qualifying_band_count": qualifying,
        "equity_variance_pct": variance,
        "equity_flag": (qualifying >= 2
                        and variance > cycle["equity_variance_threshold_pct"]),
    })
    return guards.single("recalibration_review", review)


@bp.route("/recalibration-reviews/<review_id>/decision", methods=["POST"])
def decide_review(review_id):
    actor = middleware.authorize((WORKPLACE_PROGRAM_OFFICE, COMPLIANCE_AUDITOR))
    review = middleware.must_exist("recalibration_review", review_id)
    cycle = db.get("policy_cycle", review["policy_cycle_id"])

    if actor.user_id == review["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the submitter of a review may not decide it")

    payload = middleware.body()
    decision = middleware.req_enum(payload, "decision", ("ADOPT", "REJECT"))
    expected_version = middleware.req_int(payload, "expected_policy_cycle_version")
    decision_reason = middleware.opt_string(payload, "decision_reason", 1, None)

    guards.occ_check(expected_version, cycle, "policy_cycle")
    if review["state"] != "SUBMITTED":
        fail("ERR_REVIEW_NOT_SUBMITTED", "recalibration review is not SUBMITTED")
    if cycle["posture"] != "RECALIBRATING":
        fail("ERR_CYCLE_NOT_RECALIBRATING", "policy cycle posture is not RECALIBRATING")

    teams = db.find("team", policy_cycle_id=cycle["id"])
    teams.sort(key=lambda t: (t["team_code"], db.seq_key(t)))
    if decision == "ADOPT":
        delta = review["proposed_days_in_office_delta"]
        for team in teams:
            if (team["expected_days_in_office_per_week"] + delta) < cycle["days_in_office_floor"]:
                fail("ERR_BELOW_DAYS_FLOOR",
                     "the proposed delta would drive a team below the cycle days_in_office_floor")
        if review["equity_flag"]:
            fail("ERR_EQUITY_FLAG_BLOCKS_ADOPTION",
                 "a review carrying an equity flag may not be adopted")

    changes = {
        "state": "ADOPTED" if decision == "ADOPT" else "REJECTED",
        "decided_by_user_id": actor.user_id,
    }
    if decision_reason is not None:
        changes["decision_reason"] = decision_reason
    db.apply_changes(review, changes)

    if decision == "ADOPT":
        delta = review["proposed_days_in_office_delta"]
        for team in teams:
            shifted = team["expected_days_in_office_per_week"] + delta
            shifted = max(0, min(5, shifted))
            entitlement = calc.team_seat_entitlement(team["headcount_planned"], shifted)
            db.apply_changes(team, dict({"expected_days_in_office_per_week": shifted},
                                        **entitlement))
    db.apply_changes(cycle, {"posture": "OPEN"})
    return guards.single("recalibration_review", review)


@bp.route("/recalibration-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("recalibration_review", review_id)
    return guards.single("recalibration_review", row)


@bp.route("/recalibration-reviews", methods=["GET"])
def list_reviews():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("recalibration_review")
    for arg in ("policy_cycle_id", "state"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("recalibration_review", rows)

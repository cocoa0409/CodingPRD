"""Accreditation reviews (PRD 3.3)."""

from flask import Blueprint

import calc
from auth import (
    authenticate,
    require_role,
    forbidden,
    ALL_ROLES,
    ROLE_ASSOCIATION_STAFF,
    ROLE_REVIEW_TEAM_LEAD,
)
from db import store, base_record, touch
from errors import ApiError
from routes_states import get_state_or_404
from serialize import serialize_review
from util import get_body, req_str, req_ts, req_count_pair, ok_object, paginate

bp = Blueprint("reviews", __name__)


def get_review_or_404(review_id):
    rv = store.reviews.get(review_id)
    if rv is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "Review not found: %s" % review_id, 404)
    return rv


@bp.post("/naic/reviews")
def create_review():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    # Stage 4 body reference resolution precedes stage 5 shape.
    state = None
    if body.get("state_id") is not None:
        if isinstance(body["state_id"], str):
            state = store.states.get(body["state_id"])
        if state is None:
            raise ApiError("ERR_STATE_NOT_FOUND", "state_id does not resolve", 404)
    req_str(body, "state_id")
    period_start = req_ts(body, "period_start")
    period_end = req_ts(body, "period_end")
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "period_end must be strictly after period_start",
            400,
        )
    team_lead_id = req_str(body, "team_lead_id")
    compliant, total = req_count_pair(
        body, "self_assessment_compliant", "self_assessment_total"
    )
    own = [r for r in store.reviews.values() if r["state_id"] == state["id"]]
    # Stage 8 business safety: reviewer rotation against the most recent
    # FINAL_PASS / FINAL_FAIL review of this state.
    finals = [r for r in own if r["status"] in ("FINAL_PASS", "FINAL_FAIL")]
    if finals:
        most_recent = max(finals, key=lambda r: r["_seq"])
        if most_recent["team_lead_id"] == team_lead_id:
            raise ApiError(
                "ERR_REVIEWER_ROTATION_REQUIRED",
                "team_lead_id must differ from the lead of the most recent finalized review",
                422,
            )
    # Stage 11a: closed-interval period overlap (touching counts as overlap).
    for r in own:
        if period_start <= r["period_end"] and r["period_start"] <= period_end:
            raise ApiError(
                "ERR_REVIEW_WINDOW_OVERLAP",
                "Review period intersects another review of this state",
                409,
            )
    # Stage 11b: gap to the most recent prior period_end must be >= 180 days.
    prior_ends = [r["period_end"] for r in own if r["period_end"] < period_start]
    if prior_ends and period_start - max(prior_ends) < calc.MIN_REVIEW_GAP:
        raise ApiError(
            "ERR_REVIEW_GAP_TOO_SHORT",
            "Fewer than 180 days since the state's most recent prior review period",
            422,
        )
    rec = base_record()
    rec.update({
        "state_id": state["id"],
        "period_start": period_start,
        "period_end": period_end,
        "team_lead_id": team_lead_id,
        "self_assessment_compliant": compliant,
        "self_assessment_total": total,
        "desk_score": calc.score_pct(compliant, total),
        "findings_compliant": None,
        "findings_total": None,
        "onsite_score": None,
        "proposed_outcome": None,
        "origin": "MANUAL",
        "status": "SCHEDULED",
    })
    store.reviews[rec["id"]] = rec
    return ok_object(serialize_review(rec), 201)


@bp.get("/naic/states/<state_id>/reviews")
def list_state_reviews(state_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    state = get_state_or_404(state_id)
    rvs = [r for r in store.reviews.values() if r["state_id"] == state["id"]]
    return paginate(rvs, serialize_review)


@bp.post("/naic/reviews/<review_id>/issue-findings")
def issue_findings(review_id):
    principal = authenticate()
    require_role(principal, {ROLE_REVIEW_TEAM_LEAD})
    review = get_review_or_404(review_id)
    # Resource-dependent ownership, evaluated right after path resolution; a
    # null team_lead_id (AUTO_COVERAGE) can never match any header.
    if review["team_lead_id"] is None or principal.user_id != review["team_lead_id"]:
        forbidden("X-User-ID must equal the review's team_lead_id")
    body = get_body()
    compliant, total = req_count_pair(body, "findings_compliant", "findings_total")
    if review["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_REVIEW_NOT_SCHEDULED",
            "Review %s is not SCHEDULED" % review_id,
            409,
        )
    review["findings_compliant"] = compliant
    review["findings_total"] = total
    review["onsite_score"] = calc.score_pct(compliant, total)
    review["proposed_outcome"] = calc.proposed_outcome_for(review["onsite_score"])
    review["status"] = "FINDINGS_ISSUED"
    touch(review)
    return ok_object(serialize_review(review), 200)


@bp.post("/naic/reviews/<review_id>/finalize")
def finalize_review(review_id):
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    review = get_review_or_404(review_id)
    if review["status"] != "FINDINGS_ISSUED":
        raise ApiError(
            "ERR_REVIEW_NOT_FINDINGS_ISSUED",
            "Review %s is not FINDINGS_ISSUED" % review_id,
            409,
        )
    state = store.states.get(review["state_id"])
    if review["proposed_outcome"] == "PASS":
        review["status"] = "FINAL_PASS"
        if state is not None:
            state["accreditation_status"] = "ACCREDITED"
            state["consecutive_fail_count"] = 0
            touch(state)
    else:
        review["status"] = "FINAL_FAIL"
        if state is not None:
            state["consecutive_fail_count"] += 1
            if state["consecutive_fail_count"] == 1:
                state["accreditation_status"] = "PROBATION"
            elif state["consecutive_fail_count"] >= 2:
                state["accreditation_status"] = "SUSPENDED"
            touch(state)
    touch(review)
    return ok_object(serialize_review(review), 200)

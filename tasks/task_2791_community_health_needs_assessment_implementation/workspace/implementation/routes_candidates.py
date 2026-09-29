"""Priority candidates: nomination, scoring, selection and deferral."""

from decimal import Decimal

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  ok, ok_list, paginate, public, sorted_asc, touch, v_enum,
                  v_num, v_str)

bp = Blueprint("candidates", __name__)


@bp.post("/priority-candidates")
def create_candidate():
    authenticate([K.CBO])
    body = body_or_empty()
    cycle_id = v_str(body, "cycle_id", 1, None)
    indicator_id = v_str(body, "indicator_id", 1, None)
    capacity = v_num(body, "hospital_capacity_score", 0, 100, places=2)

    cycle = D.cycle_or_404(cycle_id)
    indicator = D.indicator_or_404(indicator_id)
    D.gate_child_write(cycle, restricted=True)
    if cycle["status"] != "PRIORITIZATION":
        fail("ERR_INVALID_STATE")

    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "indicator_id": indicator["id"],
        "hospital_capacity_score": capacity,
        "scoring_variant": None,
        "severity_input": None,
        "disparity_points": None,
        "community_concern_index": None,
        "composite_score": None,
        "status": "DRAFT",
        "concern_input_dirty": False,
        "selection_rationale": None,
        "defer_reason": None,
        "strategy_count": 0,
    })
    db.candidates[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/priority-candidates")
def list_candidates():
    authenticate([K.CBO, K.BC, K.CO])
    rows = list(db.candidates.values())
    rows = filter_eq(rows, "cycle_id")
    rows = filter_eq(rows, "indicator_id")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/priority-candidates/<candidate_id>")
def get_candidate(candidate_id):
    authenticate([K.CBO, K.BC, K.CO])
    return ok(public(D.candidate_or_404(candidate_id)))


@bp.post("/priority-candidates/<candidate_id>/score")
def score_candidate(candidate_id):
    authenticate([K.CBO])
    cand = D.candidate_or_404(candidate_id)
    body = body_or_empty()
    variant = v_enum(body, "scoring_variant", K.SCORING_VARIANTS)

    cycle = D.cycle_of_candidate(cand)
    D.gate_child_write(cycle, restricted=True)
    if cand["status"] not in ("DRAFT", "SCORED", "SCORE_INVALIDATED"):
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] != "PRIORITIZATION":
        fail("ERR_INVALID_STATE")

    indicator = db.indicators.get(cand["indicator_id"])
    if indicator is None or indicator["data_state"] != "SUFFICIENT":
        fail("ERR_INDICATOR_DATA_INSUFFICIENT")

    concern = D.community_concern_index(cycle, indicator["domain"])
    if concern is None:
        fail("ERR_NO_DOMAIN_INPUT")

    severity = indicator["severity_score"]
    disparity = D.disparity_points_for(indicator)
    composite = D.composite_score(variant, severity, disparity, concern,
                                  cand["hospital_capacity_score"])

    cand["scoring_variant"] = variant
    cand["severity_input"] = severity
    cand["disparity_points"] = disparity
    cand["community_concern_index"] = concern
    cand["composite_score"] = composite
    cand["status"] = "SCORED"
    cand["concern_input_dirty"] = False
    touch(cand)
    D.sync_cycle(cycle)
    return ok(public(cand))


@bp.post("/priority-candidates/<candidate_id>/select")
def select_candidate(candidate_id):
    authenticate([K.CBO])
    cand = D.candidate_or_404(candidate_id)
    body = body_or_empty()
    rationale = v_str(body, "selection_rationale", 1, None)

    cycle = D.cycle_of_candidate(cand)
    D.gate_child_write(cycle, restricted=True)
    if cand["status"] != "SCORED":
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] != "PRIORITIZATION":
        fail("ERR_INVALID_STATE")
    if cand["concern_input_dirty"]:
        fail("ERR_STALE_CONCERN_INPUT")
    if cand["composite_score"] is None or \
            Decimal(cand["composite_score"]) < Decimal(K.SELECTION_THRESHOLD):
        fail("ERR_PRIORITY_SCORE_BELOW_THRESHOLD")

    cand["selection_rationale"] = rationale
    cand["status"] = "SELECTED"
    touch(cand)
    D.sync_cycle(cycle)
    return ok(public(cand))


@bp.post("/priority-candidates/<candidate_id>/defer")
def defer_candidate(candidate_id):
    authenticate([K.CBO])
    cand = D.candidate_or_404(candidate_id)
    body = body_or_empty()
    reason = v_str(body, "reason", 1, None)

    cycle = D.cycle_of_candidate(cand)
    D.gate_child_write(cycle, restricted=True)
    if cand["status"] not in ("DRAFT", "SCORED", "SELECTED", "SCORE_INVALIDATED"):
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] != "PRIORITIZATION":
        fail("ERR_INVALID_STATE")

    was_selected = cand["status"] == "SELECTED"
    cand["defer_reason"] = reason
    cand["status"] = "DEFERRED"
    touch(cand)
    if was_selected:
        for strat in sorted(db.strategies.values(), key=lambda s: s["_seq"]):
            if strat["candidate_id"] != cand["id"]:
                continue
            if strat["approval_state"] in ("DRAFT", "RETURNED"):
                strat["approval_state"] = "SUPERSEDED"
                touch(strat)
    D.sync_cycle(cycle)
    return ok(public(cand))

"""Implementation strategies, their measurable objectives, and the execution axis."""

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  now_iso, ok, ok_list, paginate, public, sorted_asc, touch,
                  v_date, v_enum, v_int, v_num, v_str)

bp = Blueprint("strategies", __name__)


@bp.post("/implementation-strategies")
def create_strategy():
    authenticate([K.CBO])
    body = body_or_empty()
    candidate_id = v_str(body, "candidate_id", 1, None)
    title = v_str(body, "title", 1, 160)
    authorized = v_int(body, "authorized_budget_cents", 0)
    expected = v_int(body, "expected_candidate_version", 0)

    cand = D.candidate_or_404(candidate_id)
    if expected != cand["version"]:
        fail("ERR_STALE_CANDIDATE_VERSION")

    cycle = D.cycle_of_candidate(cand)
    D.gate_child_write(cycle, restricted=True)
    if cand["status"] != "SELECTED":
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] != "STRATEGY_DEVELOPMENT":
        fail("ERR_INVALID_STATE")

    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "title": title,
        "authorized_budget_cents": authorized,
        "budget_available_cents": authorized,
        "approval_state": "DRAFT",
        "execution_state": "NOT_STARTED",
        "superseded_by_strategy_id": None,
        "submitted_at": None,
        "approved_at": None,
        "active_objective_count": 0,
        "execution_note": None,
    })
    db.strategies[rec["id"]] = rec

    # A newer strategy retires the candidate's earlier unsubmitted attempt.
    for older in sorted(db.strategies.values(), key=lambda s: s["_seq"]):
        if older["id"] == rec["id"] or older["candidate_id"] != cand["id"]:
            continue
        if older["approval_state"] not in ("DRAFT", "RETURNED"):
            continue
        older["approval_state"] = "SUPERSEDED"
        older["superseded_by_strategy_id"] = rec["id"]
        touch(older)
        for com in sorted(D.commitments_of_strategy(older), key=lambda c: c["_seq"]):
            if com["status"] == "PENDING":
                D.release_commitment(com, K.REASON_STRATEGY_SUPERSEDED)

    cand["strategy_count"] += 1
    touch(cand)
    D.sync_cycle(cycle)
    return ok(public(rec), 201)


@bp.get("/implementation-strategies")
def list_strategies():
    authenticate([K.CBO, K.BC, K.CO])
    rows = list(db.strategies.values())
    rows = filter_eq(rows, "candidate_id")
    rows = filter_eq(rows, "superseded_by_strategy_id")
    rows = filter_eq(rows, "approval_state")
    rows = filter_eq(rows, "execution_state")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/implementation-strategies/<strategy_id>")
def get_strategy(strategy_id):
    authenticate([K.CBO, K.BC, K.CO])
    return ok(public(D.strategy_or_404(strategy_id)))


@bp.post("/implementation-strategies/<strategy_id>/submit")
def submit_strategy(strategy_id):
    authenticate([K.CBO])
    strat = D.strategy_or_404(strategy_id)
    body_or_empty()
    cycle = D.cycle_of_strategy(strat)
    D.gate_child_write(cycle, restricted=True)
    if strat["approval_state"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] != "STRATEGY_DEVELOPMENT":
        fail("ERR_INVALID_STATE")
    if not any(o["status"] == "DRAFT" for o in D.objectives_of_strategy(strat)):
        fail("ERR_STRATEGY_SET_INCOMPLETE")
    strat["approval_state"] = "SUBMITTED"
    strat["submitted_at"] = now_iso()
    touch(strat)
    return ok(public(strat))


@bp.post("/implementation-strategies/<strategy_id>/objectives")
def create_objective(strategy_id):
    authenticate([K.CBO])
    strat = D.strategy_or_404(strategy_id)
    body = body_or_empty()
    metric_name = v_str(body, "metric_name", 1, 160)
    baseline = v_num(body, "baseline_value", 0, None, places=4)
    target = v_num(body, "target_value", 0, None, places=4)
    target_date = v_date(body, "target_date")

    cycle = D.cycle_of_strategy(strat)
    D.gate_child_write(cycle, restricted=True)
    if strat["approval_state"] not in ("DRAFT", "RETURNED"):
        fail("ERR_STRATEGY_LOCKED")
    if cycle is None or cycle["status"] != "STRATEGY_DEVELOPMENT":
        fail("ERR_INVALID_STATE")

    rec = new_record()
    rec.update({
        "strategy_id": strat["id"],
        "metric_name": metric_name,
        "baseline_value": baseline,
        "target_value": target,
        "target_date": target_date.isoformat(),
        "actual_value": None,
        "as_of_date": None,
        "attainment_pct": None,
        "attainment_status": "PENDING",
        "status": "DRAFT",
        "baseline_locked_at": None,
    })
    db.objectives[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/implementation-strategies/<strategy_id>/objectives")
def list_strategy_objectives(strategy_id):
    authenticate([K.CBO, K.BC, K.CO])
    strat = D.strategy_or_404(strategy_id)
    rows = [o for o in db.objectives.values() if o["strategy_id"] == strat["id"]]
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/strategy-objectives")
def list_objectives():
    authenticate([K.CBO, K.BC, K.CO])
    rows = list(db.objectives.values())
    rows = filter_eq(rows, "strategy_id")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/strategy-objectives/<objective_id>")
def get_objective(objective_id):
    authenticate([K.CBO, K.BC, K.CO])
    return ok(public(D.objective_or_404(objective_id)))


@bp.post("/strategy-objectives/<objective_id>/report-progress")
def report_progress(objective_id):
    authenticate([K.CBO])
    obj = D.objective_or_404(objective_id)
    body = body_or_empty()
    actual = v_num(body, "actual_value", 0, None, places=4)
    as_of = v_date(body, "as_of_date")

    cycle = D.cycle_of_objective(obj)
    D.gate_frozen(cycle)
    if obj["status"] not in ("ACTIVE", "REVISED"):
        fail("ERR_INVALID_STATE")

    obj["actual_value"] = actual
    obj["as_of_date"] = as_of.isoformat()
    D.compute_attainment(obj)
    touch(obj)
    return ok(public(obj))


LIVE_STATES = ("ON_TRACK", "AT_RISK", "BEHIND")


@bp.post("/implementation-strategies/<strategy_id>/execution-status")
def change_execution_status(strategy_id):
    authenticate([K.CBO])
    strat = D.strategy_or_404(strategy_id)
    body = body_or_empty()
    to_state = v_enum(body, "to_execution_state", K.EXECUTION_STATES)
    note = v_str(body, "execution_note", 0, None, required=False)

    cycle = D.cycle_of_strategy(strat)
    # An execution-status change is deliberately exempt from the RESTRICTED gate:
    # clearing a suspension is the only route back to an OPEN posture.
    D.gate_frozen(cycle)

    # §3.8 states the approval requirement first; both checks live on the target
    # row's own state, so the approval axis is evaluated before the execution axis.
    if strat["approval_state"] != "APPROVED":
        fail("ERR_STRATEGY_NOT_APPROVED")

    current = strat["execution_state"]
    clearing_suspension = False
    if to_state in LIVE_STATES:
        if current in LIVE_STATES:
            pass
        elif current == "SUSPENDED_PENDING_REVIEW" and to_state == "ON_TRACK":
            clearing_suspension = True
        else:
            fail("ERR_INVALID_STATE")
    elif to_state == "COMPLETED":
        if current not in LIVE_STATES:
            fail("ERR_INVALID_STATE")
    elif to_state == "DISCONTINUED":
        if current not in LIVE_STATES + ("SUSPENDED_PENDING_REVIEW",):
            fail("ERR_INVALID_STATE")
    else:
        fail("ERR_INVALID_STATE")

    if clearing_suspension:
        cand = db.candidates.get(strat["candidate_id"])
        if cand is None or cand["status"] == "SCORE_INVALIDATED":
            fail("ERR_INVALID_STATE")

    if to_state == "COMPLETED":
        objectives = D.objectives_of_strategy(strat)
        for obj in objectives:
            if obj["status"] not in ("ACTIVE", "REVISED") or obj["attainment_status"] == "PENDING":
                fail("ERR_OBJECTIVE_PROGRESS_MISSING")

    strat["execution_state"] = to_state
    if note is not None:
        strat["execution_note"] = note
    touch(strat)

    if to_state == "DISCONTINUED":
        for com in sorted(D.commitments_of_strategy(strat), key=lambda c: c["_seq"]):
            if com["status"] in ("PENDING", "COMMITTED"):
                D.release_commitment(com, K.REASON_STRATEGY_DISCONTINUED)

    D.sync_cycle(cycle)
    return ok(public(strat))

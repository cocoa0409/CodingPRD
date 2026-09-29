"""Assessment-cycle endpoints: create, list, read, advance, board action,
publish, file-return, and the cycle-scoped progress-evaluation list."""

from flask import Blueprint, g

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  now_iso, ok, ok_list, paginate, public, raw_field, sorted_asc,
                  sorted_desc, touch, v_bool, v_enum, v_int, v_num, v_str)

bp = Blueprint("cycles", __name__)

ALL_ROLES = K.ROLES


def new_cycle_record(fiscal_year, service_area_name, ratio, opex):
    rec = new_record()
    rec.update({
        "fiscal_year": fiscal_year,
        "service_area_name": service_area_name,
        "prior_year_cost_to_charge_ratio": ratio,
        "total_operating_expense_cents": opex,
        "status": "DRAFT",
        "posture": "OPEN",
        "completed_interview_count": 0,
        "sufficient_indicator_count": 0,
        "selected_priority_count": 0,
        "review_flag_count": 0,
        "board_deferral_count": 0,
        "mid_cycle_adjustment_count": 0,
        "annual_report_count": 0,
        "adopted_at": None,
        "adoption_board_user_id": None,
        "votes_for_at_adoption": None,
        "votes_against_at_adoption": None,
        "public_url": None,
        "public_comment_channel": None,
        "public_availability_met": False,
        "published_at": None,
        "return_form_id": None,
        "filed_at": None,
    })
    return rec


@bp.post("/assessment-cycles")
def create_cycle():
    authenticate([K.CBO])
    body = body_or_empty()
    fiscal_year = v_int(body, "fiscal_year", 2000, 2100)
    service_area_name = v_str(body, "service_area_name", 1, 120)
    ratio = v_num(body, "prior_year_cost_to_charge_ratio", 0, 1,
                  exact_places=4, exclusive_lo=True)
    opex = v_int(body, "total_operating_expense_cents", 1)
    for existing in db.cycles.values():
        if existing["fiscal_year"] == fiscal_year:
            fail("ERR_DUPLICATE_FISCAL_YEAR")
    rec = new_cycle_record(fiscal_year, service_area_name, ratio, opex)
    db.cycles[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/assessment-cycles")
def list_cycles():
    authenticate(ALL_ROLES)
    rows = list(db.cycles.values())
    rows = filter_eq(rows, "fiscal_year")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_desc(rows))
    return ok_list(data, page)


@bp.get("/assessment-cycles/<cycle_id>")
def get_cycle(cycle_id):
    authenticate(ALL_ROLES)
    return ok(public(D.cycle_or_404(cycle_id)))


@bp.get("/assessment-cycles/<cycle_id>/progress-evaluations")
def list_cycle_evaluations(cycle_id):
    authenticate([K.CBO, K.BC, K.CO, K.PV])
    cycle = D.cycle_or_404(cycle_id)
    rows = [e for e in db.evaluations.values() if e["cycle_id"] == cycle["id"]]
    rows = filter_eq(rows, "eval_type")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


def _defer_unselected_candidates(cycle):
    """Reaching STRATEGY_DEVELOPMENT locks the priority list by cascade."""
    for cand in sorted(db.candidates.values(), key=lambda c: c["_seq"]):
        if cand["cycle_id"] != cycle["id"]:
            continue
        if cand["status"] in ("DRAFT", "SCORED", "SCORE_INVALIDATED"):
            cand["status"] = "DEFERRED"
            cand["defer_reason"] = K.REASON_NOT_SELECTED_AT_PRIORITY_LOCK
            touch(cand)


def _strategy_set_complete(cycle):
    selected = [c for c in db.candidates.values()
                if c["cycle_id"] == cycle["id"] and c["status"] == "SELECTED"]
    for cand in selected:
        ok_for_candidate = False
        for strat in db.strategies.values():
            if strat["candidate_id"] != cand["id"]:
                continue
            if strat["approval_state"] != "SUBMITTED":
                continue
            for obj in D.objectives_of_strategy(strat):
                if obj["status"] in ("DRAFT", "ACTIVE"):
                    ok_for_candidate = True
                    break
            if ok_for_candidate:
                break
        if not ok_for_candidate:
            return False
    return True


@bp.post("/assessment-cycles/<cycle_id>/advance")
def advance_cycle(cycle_id):
    # Rung 2 refinement: the acting role must equal the declared actor of the
    # requested transition, so the raw to_status is read before body validation.
    authenticate([K.CBO, K.CO])
    body = body_or_empty()
    requested = raw_field(body, "to_status")
    if requested == "CLOSED":
        if g.role != K.CO:
            fail("ERR_UNAUTHORIZED", "A to_status of CLOSED requires ComplianceOfficer.")
    elif g.role != K.CBO:
        fail("ERR_UNAUTHORIZED", "This transition requires CommunityBenefitOfficer.")

    cycle = D.cycle_or_404(cycle_id)
    to_status = v_enum(body, "to_status", K.CYCLE_STATUSES)

    # posture never gates a phase advance -- it is a mutation of the cycle itself
    if K.ADVANCE_CHAIN.get(cycle["status"]) != to_status:
        fail("ERR_INVALID_PHASE_TRANSITION")

    if to_status == "BOARD_REVIEW" and not _strategy_set_complete(cycle):
        fail("ERR_STRATEGY_SET_INCOMPLETE")
    if to_status == "CLOSED":
        has_annual = any(e["cycle_id"] == cycle["id"] and e["eval_type"] == "ANNUAL"
                         and e["status"] == "PUBLISHED" for e in db.evaluations.values())
        if not has_annual:
            fail("ERR_ANNUAL_REPORT_MISSING")
    if to_status == "INPUT_GATHERING" and cycle["sufficient_indicator_count"] < 1:
        fail("ERR_INSUFFICIENT_INDICATOR_COVERAGE")
    if to_status == "PRIORITIZATION" and cycle["completed_interview_count"] < 1:
        fail("ERR_NO_COMMUNITY_INPUT")
    if to_status == "STRATEGY_DEVELOPMENT" and cycle["selected_priority_count"] < 1:
        fail("ERR_NO_SELECTED_PRIORITY")

    cycle["status"] = to_status
    touch(cycle)
    if to_status == "STRATEGY_DEVELOPMENT":
        _defer_unselected_candidates(cycle)
    if to_status == "CLOSED":
        D.closeout_cascade(cycle)
    D.sync_cycle(cycle, force=True)
    return ok(public(cycle))


@bp.post("/assessment-cycles/<cycle_id>/board-action")
def board_action(cycle_id):
    user_id, _role = authenticate([K.BC])
    cycle = D.cycle_or_404(cycle_id)
    body = body_or_empty()
    action_type = v_enum(body, "action_type", K.BOARD_ACTION_TYPES)
    quorum_present = v_bool(body, "quorum_present")
    votes_for = v_int(body, "votes_for", 0)
    votes_against = v_int(body, "votes_against", 0)
    v_str(body, "note", 0, None, required=False)

    if cycle["status"] != "BOARD_REVIEW":
        fail("ERR_INVALID_STATE")
    if not quorum_present:
        fail("ERR_QUORUM_NOT_MET")
    if action_type == "ADOPT" and not votes_for > votes_against:
        fail("ERR_ADOPTION_VOTE_FAILED")

    if action_type == "DEFER":
        cycle["status"] = "STRATEGY_DEVELOPMENT"
        cycle["board_deferral_count"] += 1
        touch(cycle)
        for strat in sorted(D.strategies_of_cycle(cycle), key=lambda s: s["_seq"]):
            if strat["approval_state"] == "SUBMITTED":
                strat["approval_state"] = "RETURNED"
                touch(strat)
    else:
        stamp = now_iso()
        cycle["status"] = "ADOPTED"
        cycle["adopted_at"] = stamp
        cycle["adoption_board_user_id"] = user_id
        cycle["votes_for_at_adoption"] = votes_for
        cycle["votes_against_at_adoption"] = votes_against
        touch(cycle)
        D.adoption_cascade(cycle)
    D.sync_cycle(cycle, force=True)
    return ok(public(cycle))


@bp.post("/assessment-cycles/<cycle_id>/publish")
def publish_cycle(cycle_id):
    authenticate([K.CBO])
    cycle = D.cycle_or_404(cycle_id)
    body = body_or_empty()
    public_url = v_str(body, "public_url", 1, None)
    channel = v_str(body, "public_comment_channel", 1, None)
    if cycle["status"] != "ADOPTED" or cycle["adopted_at"] is None:
        fail("ERR_INVALID_STATE")
    cycle["public_url"] = public_url
    cycle["public_comment_channel"] = channel
    cycle["published_at"] = now_iso()
    cycle["public_availability_met"] = True
    cycle["status"] = "PUBLISHED"
    touch(cycle)
    D.sync_cycle(cycle, force=True)
    return ok(public(cycle))


@bp.post("/assessment-cycles/<cycle_id>/file-return")
def file_return(cycle_id):
    authenticate([K.CO])
    cycle = D.cycle_or_404(cycle_id)
    body = body_or_empty()
    return_form_id = v_str(body, "return_form_id", 1, None)
    if cycle["status"] not in ("ADOPTED", "PUBLISHED"):
        fail("ERR_INVALID_STATE")
    if not cycle["public_availability_met"]:
        fail("ERR_PUBLIC_AVAILABILITY_NOT_MET")
    locked = [r for r in db.reports.values()
              if r["cycle_id"] == cycle["id"] and r["status"] == "LOCKED"]
    if len(locked) != 1:
        fail("ERR_REPORT_NOT_LOCKED")
    stamp = now_iso()
    cycle["return_form_id"] = return_form_id
    cycle["filed_at"] = stamp
    cycle["status"] = "FILED"
    touch(cycle)
    report = locked[0]
    report["status"] = "FILED"
    report["filed_at"] = stamp
    touch(report)
    D.sync_cycle(cycle, force=True)
    return ok(public(cycle))

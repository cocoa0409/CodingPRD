"""Progress evaluations plus the logical-clock control endpoint."""

from decimal import Decimal

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  no_content, now_iso, ok, ok_list, paginate, public, set_clock,
                  sorted_asc, touch, v_enum, v_instant, v_int, v_str)

bp = Blueprint("evaluations", __name__)

REVISION_THRESHOLD = Decimal(K.PARTIAL_THRESHOLD)


@bp.post("/progress-evaluations")
def create_evaluation():
    authenticate([K.CBO])
    body = body_or_empty()
    cycle_id = v_str(body, "cycle_id", 1, None)
    eval_type = v_enum(body, "eval_type", K.EVAL_TYPES)
    period_year = v_int(body, "period_year", 2000, 2100)
    findings = v_str(body, "findings_summary", 1, None, required=False)

    cycle = D.cycle_or_404(cycle_id)
    D.gate_frozen(cycle)
    # §3.8: evaluations carry no cycle-phase gate at creation time.
    for other in db.evaluations.values():
        if (other["cycle_id"] == cycle["id"]
                and other["eval_type"] == eval_type
                and other["period_year"] == period_year):
            fail("ERR_DUPLICATE_EVALUATION_PERIOD")

    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "eval_type": eval_type,
        "period_year": period_year,
        "findings_summary": findings,
        "status": "DRAFT",
        "public_url": None,
        "published_at": None,
        "objectives_revised_count": 0,
    })
    db.evaluations[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/progress-evaluations")
def list_evaluations():
    authenticate([K.CBO, K.BC, K.CO])
    rows = list(db.evaluations.values())
    rows = filter_eq(rows, "cycle_id")
    rows = filter_eq(rows, "eval_type")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/progress-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    authenticate([K.CBO, K.BC, K.CO, K.PV])
    return ok(public(D.evaluation_or_404(evaluation_id)))


@bp.post("/progress-evaluations/<evaluation_id>/publish")
def publish_evaluation(evaluation_id):
    authenticate([K.CBO])
    ev = D.evaluation_or_404(evaluation_id)
    body = body_or_empty()
    public_url = v_str(body, "public_url", 1, None)

    cycle = D.cycle_or_404(ev["cycle_id"]) if ev["cycle_id"] in db.cycles else None
    D.gate_frozen(cycle)
    if ev["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] not in ("ADOPTED", "PUBLISHED", "FILED"):
        fail("ERR_INVALID_STATE")

    ev["public_url"] = public_url
    ev["published_at"] = now_iso()
    ev["status"] = "PUBLISHED"

    if ev["eval_type"] == "ANNUAL":
        cycle["annual_report_count"] += 1
        touch(cycle)
    else:
        cycle["mid_cycle_adjustment_count"] += 1
        touch(cycle)
        revised = 0
        for strat in sorted(D.strategies_of_cycle(cycle), key=lambda s: s["_seq"]):
            for obj in sorted(D.objectives_of_strategy(strat), key=lambda o: o["_seq"]):
                if obj["status"] != "ACTIVE":
                    continue
                pct = obj["attainment_pct"]
                if pct is None or Decimal(pct) >= REVISION_THRESHOLD:
                    continue
                obj["status"] = "REVISED"
                touch(obj)
                revised += 1
                if strat["execution_state"] == "ON_TRACK":
                    strat["execution_state"] = "BEHIND"
                    touch(strat)
        ev["objectives_revised_count"] = revised

    touch(ev)
    D.sync_cycle(cycle)
    return ok(public(ev))


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate([K.CBO, K.DS, K.BC, K.CO])
    body = body_or_empty()
    moment = v_instant(body, "to_iso8601")
    set_clock(moment)
    return no_content()

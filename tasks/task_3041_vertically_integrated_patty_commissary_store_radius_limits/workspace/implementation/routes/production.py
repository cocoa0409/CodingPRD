"""ProductionRun routes."""

import math

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_BATCHES_NOT_DELIVERED,
    ERR_CAPACITY_EXCEEDED,
    ERR_RUN_INVALID_STATE,
    conflict,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    parse_datetime,
    req_field,
    req_int,
    touch,
)

bp = Blueprint("production", __name__)


@bp.route("/commissaries/<cid>/production-runs", methods=["POST"])
def create_production_run(cid):
    require_roles("CommissaryPlanner")
    c = domain.get_commissary(cid)
    body = get_json_body()
    run_date = parse_datetime(req_field(body, "run_date"), "run_date")
    patties = req_int(body, "patties_planned")
    buns = req_int(body, "buns_planned")
    produce = req_int(body, "produce_units_planned")
    # Capacity + raw-beef gates (tier 17), all ERR_CAPACITY_EXCEEDED.
    if patties > c["daily_patty_capacity"]:
        raise unprocessable(ERR_CAPACITY_EXCEEDED, "patties_planned exceeds daily_patty_capacity")
    if buns > c["daily_bun_capacity"]:
        raise unprocessable(ERR_CAPACITY_EXCEEDED, "buns_planned exceeds daily_bun_capacity")
    if produce > c["daily_produce_capacity"]:
        raise unprocessable(ERR_CAPACITY_EXCEEDED, "produce_units_planned exceeds daily_produce_capacity")
    beef_lbs_required = math.ceil(patties / calc.PATTIES_PER_LB) if patties > 0 else 0
    if c["raw_beef_lbs_on_hand"] > 0 and beef_lbs_required > c["raw_beef_lbs_on_hand"]:
        raise unprocessable(ERR_CAPACITY_EXCEEDED, "Insufficient raw beef on hand")
    r = base_entity()
    r.update({
        "commissary_id": c["id"],
        "run_date": run_date,
        "patties_planned": patties,
        "buns_planned": buns,
        "produce_units_planned": produce,
        "beef_lbs_required": beef_lbs_required,
        "status": "PLANNED",
    })
    db.production_runs[r["id"]] = r
    # Debit the raw-beef ledger; conserved.
    c["raw_beef_lbs_on_hand"] -= beef_lbs_required
    touch(c)
    return success_object(domain.ser_production_run(r), 201)


@bp.route("/commissaries/<cid>/production-runs", methods=["GET"])
def list_production_runs(cid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    c = domain.get_commissary(cid)
    items = [r for r in db.production_runs.values() if r["commissary_id"] == c["id"]]
    rd = request.args.get("run_date")
    if rd is not None:
        items = [r for r in items if r["run_date"].isoformat().startswith(rd[:10])]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_production_run(r) for r in page], limit, offset, total)


@bp.route("/production-runs/<rid>", methods=["GET"])
def get_production_run(rid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    return success_object(domain.ser_production_run(domain.get_production_run(rid)))


@bp.route("/production-runs/<rid>/complete", methods=["POST"])
def complete_run(rid):
    require_roles("CommissaryPlanner")
    r = domain.get_production_run(rid)
    if r["status"] != "PLANNED":
        raise conflict(ERR_RUN_INVALID_STATE, "Run must be PLANNED to complete")
    r["status"] = "COMPLETED"
    touch(r)
    return success_object(domain.ser_production_run(r))


@bp.route("/production-runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    require_roles("CommissaryPlanner")
    r = domain.get_production_run(rid)
    if r["status"] != "PLANNED":
        raise conflict(ERR_RUN_INVALID_STATE, "Run must be PLANNED to cancel")
    loaded = any(
        b.get("production_run_id") == r["id"] and b["status"] == "LOADED"
        for b in db.batches.values()
    )
    if loaded:
        raise conflict(ERR_BATCHES_NOT_DELIVERED, "A LOADED batch references this run")
    r["status"] = "CANCELLED"
    touch(r)
    # Compensating action: restore the conserved raw-beef ledger.
    c = db.commissaries.get(r["commissary_id"])
    if c is not None:
        c["raw_beef_lbs_on_hand"] += r["beef_lbs_required"]
        touch(c)
    return success_object(domain.ser_production_run(r))

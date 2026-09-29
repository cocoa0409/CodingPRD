"""Ammonia campaigns: schedule, approve, start, settle, abort, restate (PRD 3.4)."""
from flask import Blueprint, request

import calc
import cascade
import serialize
import validate as v
from auth import ALL_ROLES, PROCESS_ENGINEER, actor
from envelope import list_response, object_response, paging
from errors import ApiError
from guards import duplicate, filtered, load, not_frozen, state
from mutate import touch
from store import db, stamp_new
from util import D, rhu

bp = Blueprint("runs", __name__)
PREFIX = "/nitrogen-ops/production-runs"
RUN_STATUSES = ("PLANNED", "APPROVED", "RUNNING", "COMPLETED", "ABORTED")
CREATE_LIVE = ("PLANNED", "APPROVED", "RUNNING", "COMPLETED")
APPROVE_LIVE = ("APPROVED", "RUNNING", "COMPLETED")


def _plant_of(run):
    return calc.plant_of_run(run)


def _overlaps(train_id, window_start, window_end, statuses, exclude_id=None):
    """Half-open window intersection against the train's live campaigns."""
    for other in db.runs.values():
        if other["train_id"] != train_id or other["id"] == exclude_id:
            continue
        if other["status"] not in statuses:
            continue
        if other["window_start"] < window_end and other["window_end"] > window_start:
            return True
    return False


def _train_available(train):
    state(train["status"] not in ("DERATED", "DOWN_FOR_TURNAROUND"),
          "ERR_TRAIN_UNAVAILABLE")


def _charge_in_service(train):
    """Rung 13: the severity-adjusted figure of the train's ACTIVE charge."""
    charge = calc.active_charge(train["id"])
    if charge is None:
        raise ApiError("ERR_CATALYST_ACTIVITY_TOO_LOW",
                       "The reformer train carries no ACTIVE catalyst charge.")
    if calc.charge_activity_pct(charge) < calc.CATALYST_MIN_ACTIVITY_PCT:
        raise ApiError("ERR_CATALYST_ACTIVITY_TOO_LOW")
    return charge


@bp.post(PREFIX)
def create_run():
    who = actor([PROCESS_ENGINEER])
    body = v.get_body()
    train_id = v.s_id(body, "train_id")
    run_code = v.s_code(body, "run_code", 2, 16)
    window_start = v.s_dt(body, "window_start")
    window_end = v.s_dt(body, "window_end")
    target = v.s_num(body, "target_ammonia_tons", 3, gt=0)
    if window_end <= window_start:
        v.bad("window_end must be strictly after window_start.")
    train = load("trains", train_id)
    plant = calc.plant_of_train(train)
    # run_code is unique per plant, and a run reaches its plant through its train.
    plant_train_ids = {t["id"] for t in db.trains.values()
                       if t["plant_id"] == train["plant_id"]}
    duplicate("runs", "run_code", run_code,
              extra=lambda r: r["train_id"] in plant_train_ids)
    not_frozen(plant)
    _train_available(train)
    state(not _overlaps(train_id, window_start, window_end, CREATE_LIVE),
          "ERR_RUN_WINDOW_OVERLAP")
    row = {
        "train_id": train_id,
        "catalyst_charge_id": None,
        "run_code": run_code,
        "window_start": window_start,
        "window_end": window_end,
        "target_ammonia_tons": target,
        "actual_ammonia_tons": None,
        "actual_operating_hours": None,
        "consumed_gas_mmbtu": D("0.0"),
        "provisional_unit_cost_usd_per_ton": None,
        "final_unit_cost_usd_per_ton": None,
        "status": "PLANNED",
        "abort_reason": None,
        "reopen_reason": None,
        "created_by_user_id": who["user_id"],
        # Volume drawn from each hedge lot by the settlement, for the reversal.
        "_lot_draws": {},
    }
    stamp_new(row)
    db.runs[row["id"]] = row
    return object_response(serialize.run_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_run(id):
    actor(ALL_ROLES)
    return object_response(serialize.run_json(load("runs", id)))


@bp.get(PREFIX)
def list_runs():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("runs", [
        ("train_id", v.query_str("train_id")),
        ("catalyst_charge_id", v.query_str("catalyst_charge_id")),
        ("status", v.query_enum("status", RUN_STATUSES)),
    ])
    return list_response(serialize.dump("runs", rows), limit, offset)


@bp.post(PREFIX + "/<id>/approve")
def approve_run(id):
    who = actor([PROCESS_ENGINEER])
    v.get_body()
    run = load("runs", id)
    state(run["status"] == "PLANNED")
    train = db.trains[run["train_id"]]
    plant = calc.plant_of_train(train)
    not_frozen(plant)
    state(who["user_id"] != run["created_by_user_id"], "ERR_SEGREGATION_OF_DUTIES")
    _charge_in_service(train)
    _train_available(train)
    state(train["status"] in ("IDLE", "RUNNING"), "ERR_TRAIN_UNAVAILABLE")
    state(not _overlaps(run["train_id"], run["window_start"], run["window_end"],
                        APPROVE_LIVE, exclude_id=run["id"]),
          "ERR_RUN_WINDOW_OVERLAP")
    unit_cost, _, _ = calc.run_unit_cost(run, plant, "PROVISIONAL",
                                         run["target_ammonia_tons"])
    run["provisional_unit_cost_usd_per_ton"] = unit_cost
    run["status"] = "APPROVED"
    touch(run)
    return object_response(serialize.run_json(run))


@bp.post(PREFIX + "/<id>/start")
def start_run(id):
    actor([PROCESS_ENGINEER])
    v.get_body()
    run = load("runs", id)
    state(run["status"] == "APPROVED")
    state(db.clock >= run["window_start"],
          message="The logical clock has not reached window_start.")
    train = db.trains[run["train_id"]]
    plant = calc.plant_of_train(train)
    not_frozen(plant)
    charge = _charge_in_service(train)
    _train_available(train)
    state(train["status"] in ("IDLE", "RUNNING"), "ERR_TRAIN_UNAVAILABLE")
    run["catalyst_charge_id"] = charge["id"]
    run["status"] = "RUNNING"
    touch(run)
    if train["status"] == "IDLE":
        train["status"] = "RUNNING"
    touch(train)
    return object_response(serialize.run_json(run))


@bp.post(PREFIX + "/<id>/complete")
def complete_run(id):
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    tons = v.s_num(body, "actual_ammonia_tons", 3, gt=0)
    hours = v.s_num(body, "actual_operating_hours", 1, gt=0)
    run = load("runs", id)
    state(run["status"] == "RUNNING")
    state(db.clock >= run["window_start"],
          message="The logical clock has not reached window_start.")
    train = db.trains[run["train_id"]]
    plant = calc.plant_of_train(train)
    promised = calc.promised_ammonia_tons(run["id"])
    state(tons >= promised, "ERR_AMMONIA_BALANCE_EXCEEDED")
    unit_cost, draws, hedged = calc.run_unit_cost(run, plant, "FINAL", tons)
    for lot_id, draw in draws.items():
        lot = db.lots[lot_id]
        lot["consumed_mmbtu"] = lot["consumed_mmbtu"] + draw
        if calc.remaining_mmbtu(lot) <= 0:
            lot["status"] = "CLOSED"
        touch(lot)
    run["_lot_draws"] = dict(draws)
    run["actual_ammonia_tons"] = tons
    run["actual_operating_hours"] = hours
    run["consumed_gas_mmbtu"] = rhu(hedged, 1)
    run["final_unit_cost_usd_per_ton"] = unit_cost
    run["status"] = "COMPLETED"
    touch(run)
    touch(plant)
    charge = db.charges.get(run["catalyst_charge_id"])
    if charge is not None:
        touch(charge)
        derated = cascade.derate_if_spent(charge)
    else:
        derated = False
    if not derated and train["status"] == "RUNNING":
        train["status"] = "IDLE"
    touch(train)
    return object_response(serialize.run_json(run))


@bp.post(PREFIX + "/<id>/abort")
def abort_run(id):
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    reason = v.s_str(body, "abort_reason", min_len=1)
    run = load("runs", id)
    state(run["status"] in ("APPROVED", "RUNNING"))
    was_running = run["status"] == "RUNNING"
    run["status"] = "ABORTED"
    run["abort_reason"] = reason
    if not was_running:
        # PRD 3.4: aborting an APPROVED campaign withdraws its provisional price.
        run["provisional_unit_cost_usd_per_ton"] = None
    touch(run)
    if was_running:
        cascade.release_reserved_orders_of_run(run, "RUN_ABORTED")
        train = db.trains[run["train_id"]]
        if train["status"] == "RUNNING":
            train["status"] = "IDLE"
            touch(train)
    return object_response(serialize.run_json(run))


@bp.post(PREFIX + "/<id>/reopen")
def reopen_run(id):
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    reason = v.s_str(body, "reopen_reason", min_len=1)
    run = load("runs", id)
    state(run["status"] == "COMPLETED")
    consumed = any(o["run_id"] == run["id"] and o["allocation_status"] == "CONSUMED"
                   for o in db.orders.values())
    state(not consumed, "ERR_ORDER_ALREADY_PRODUCED")
    train = db.trains[run["train_id"]]
    plant = calc.plant_of_train(train)
    not_frozen(plant)
    state(train["status"] != "DOWN_FOR_TURNAROUND", "ERR_TRAIN_UNAVAILABLE")
    for lot_id, draw in run["_lot_draws"].items():
        lot = db.lots.get(lot_id)
        if lot is None:
            continue
        lot["consumed_mmbtu"] = lot["consumed_mmbtu"] - draw
        if calc.remaining_mmbtu(lot) > 0 and lot["status"] == "CLOSED":
            lot["status"] = "OPEN"
        touch(lot)
    run["_lot_draws"] = {}
    run["consumed_gas_mmbtu"] = D("0.0")
    run["final_unit_cost_usd_per_ton"] = None
    run["actual_ammonia_tons"] = None
    run["actual_operating_hours"] = None
    run["reopen_reason"] = reason
    run["status"] = "RUNNING"
    touch(run)
    touch(plant)
    cascade.release_reserved_orders_of_run(run, "RUN_REOPENED")
    charge = db.charges.get(run["catalyst_charge_id"])
    if charge is not None:
        touch(charge)
        cascade.recover_if_activity_restored(charge, resume_running=True)
    if train["status"] != "RUNNING":
        train["status"] = "RUNNING"
        touch(train)
    return object_response(serialize.run_json(run))

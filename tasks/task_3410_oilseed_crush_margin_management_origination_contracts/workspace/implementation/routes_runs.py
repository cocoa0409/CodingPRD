"""Crush runs: plan, read, list, schedule (OCC), lifecycle transitions."""
from datetime import timezone
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import (MEAL_YIELD_LBS_PER_BUSHEL, OIL_YIELD_LBS_PER_BUSHEL,
                  crush_spread, quotes3, round_int)
from envelope import success_list, success_obj
from errors import fail
from store import db, get_clock, new_id, stamp_new, to_jsonable, touch
from validate import (body_dict, paginate, req_datetime, req_int, req_month,
                      sort_created, to_int)

bp = Blueprint("runs", __name__)

RUN_TRANSITIONS = ("PLANNED", "RUNNING", "COMPLETE", "CANCELLED")


@bp.post("/api/crush-runs")
def create_run():
    require_roles("PlantScheduler")
    body = body_dict()
    # Body FK (priority 4).
    plant = None
    if body.get("plant_id") is not None:
        plant = db["plants"].get(body["plant_id"])
        if plant is None:
            fail("ERR_PLANT_NOT_FOUND", "plant_id does not resolve")
    # Shape (priority 9).
    if plant is None:
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    run_date = req_datetime(body, "run_date")
    # Canonicalize to UTC midnight of the campaign day.
    run_date = run_date.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    planned = req_int(body, "planned_bushels")
    if planned <= 0:
        fail("ERR_INVALID_REQUEST", "planned_bushels must be a positive whole number")
    month = req_month(body, "futures_month")
    # Referenced market data (priority 11): PLANNED margin from as-of quotes.
    q = quotes3(month)
    if q is None:
        fail("ERR_NO_MARKET_QUOTE",
             "as-of BEAN/OIL/MEAL quotes are required for futures_month")
    bean, oil, meal = q
    spread = crush_spread(bean, oil, meal)
    rec = {
        "id": new_id(),
        "plant_id": plant["id"],
        "run_date": run_date,
        "planned_bushels": planned,
        "futures_month": month,
        "expected_oil_lbs": planned * OIL_YIELD_LBS_PER_BUSHEL,
        "expected_meal_lbs": planned * MEAL_YIELD_LBS_PER_BUSHEL,
        "spread_cents_per_bushel": spread,
        "planned_margin_cents": round_int(Decimal(planned) * spread),
        "realized_margin_cents": None,
        "status": "PLANNED",
    }
    stamp_new(rec)
    db["runs"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/crush-runs/<rid>")
def get_run(rid):
    require_roles("PlatformAdmin", "PlantScheduler", "CrushTrader")
    rec = db["runs"].get(rid)
    if rec is None:
        fail("ERR_RUN_NOT_FOUND", "crush run not found")
    return success_obj(to_jsonable(rec))


@bp.get("/api/crush-runs")
def list_runs():
    require_roles("PlatformAdmin", "PlantScheduler", "CrushTrader")
    items = sort_created(list(db["runs"].values()))
    plant_id = request.args.get("plant_id")
    if plant_id is not None:
        items = [r for r in items if r["plant_id"] == plant_id]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(r) for r in page], limit, offset, total)


def _get_run_or_404(rid):
    rec = db["runs"].get(rid)
    if rec is None:
        fail("ERR_RUN_NOT_FOUND", "crush run not found")
    return rec


@bp.post("/api/crush-runs/<rid>/schedule")
def schedule_run(rid):
    require_roles("PlantScheduler")
    run = _get_run_or_404(rid)
    body = body_dict()
    # OCC (priority 5): evaluated before any state check.
    expected = to_int(body.get("expected_run_version"))
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_run_version is required")
    if expected != run["version"]:
        fail("ERR_STALE_RUN_VERSION",
             "expected_run_version does not match the run's current version")
    # State (priority 6).
    if run["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "run is not in PLANNED")
    # Temporal (priority 7): run date not before the current clock date.
    clock = get_clock()
    if run["run_date"].date() < clock.date():
        fail("ERR_RUN_DATE_IN_PAST",
             "run_date is before the current logical clock date")
    # Capacity (priority 10): per-day aggregate over {SCHEDULED,RUNNING,COMPLETE}.
    plant = db["plants"][run["plant_id"]]
    used = sum(r["planned_bushels"] for r in db["runs"].values()
               if r["plant_id"] == run["plant_id"]
               and r["status"] in ("SCHEDULED", "RUNNING", "COMPLETE")
               and r["run_date"] == run["run_date"])
    if used + run["planned_bushels"] > plant["daily_crush_capacity_bushels"]:
        fail("ERR_PLANT_CAPACITY_EXCEEDED",
             "plant per-day crush capacity exceeded")
    # Referenced-entity state (priority 11).
    if plant["status"] != "ACTIVE":
        fail("ERR_PLANT_NOT_ACTIVE", "plant is not ACTIVE")
    # Fiscal viability (priority 12, always last).
    if run["planned_margin_cents"] < 0:
        fail("ERR_NEGATIVE_CRUSH_MARGIN", "planned_margin_cents is negative")
    run["status"] = "SCHEDULED"
    touch(run)
    return success_obj(to_jsonable(run))


@bp.post("/api/crush-runs/<rid>/transitions")
def run_transition(rid):
    require_roles("PlantScheduler")
    run = _get_run_or_404(rid)
    body = body_dict()
    to_status = body.get("to_status")
    if to_status not in RUN_TRANSITIONS:
        fail("ERR_INVALID_REQUEST",
             "to_status must be one of PLANNED, RUNNING, COMPLETE, CANCELLED")
    current = run["status"]
    if to_status == "PLANNED":
        # Revert cycle: frees the day's aggregate capacity.
        if current != "SCHEDULED":
            fail("ERR_INVALID_STATE", "only a SCHEDULED run can revert to PLANNED")
        run["status"] = "PLANNED"
    elif to_status == "RUNNING":
        if current != "SCHEDULED":
            fail("ERR_INVALID_STATE", "only a SCHEDULED run can start")
        plant = db["plants"][run["plant_id"]]
        if plant["bean_inventory_bushels"] < run["planned_bushels"]:
            fail("ERR_INSUFFICIENT_PLANT_INVENTORY",
                 "plant bean inventory is below planned_bushels")
        plant["bean_inventory_bushels"] = (
            Decimal(plant["bean_inventory_bushels"]) - run["planned_bushels"])
        touch(plant)
        run["status"] = "RUNNING"
    elif to_status == "COMPLETE":
        if current != "RUNNING":
            fail("ERR_INVALID_STATE", "only a RUNNING run can complete")
        q = quotes3(run["futures_month"])
        if q is None:
            fail("ERR_NO_MARKET_QUOTE",
                 "as-of BEAN/OIL/MEAL quotes are required at completion")
        bean, oil, meal = q
        new_spread = crush_spread(bean, oil, meal)
        run["realized_margin_cents"] = round_int(
            Decimal(run["planned_bushels"]) * new_spread)
        run["status"] = "COMPLETE"
    else:  # CANCELLED
        if current not in ("PLANNED", "SCHEDULED"):
            fail("ERR_INVALID_STATE",
                 "only a PLANNED or SCHEDULED run can be cancelled")
        run["status"] = "CANCELLED"
    touch(run)
    return success_obj(to_jsonable(run))

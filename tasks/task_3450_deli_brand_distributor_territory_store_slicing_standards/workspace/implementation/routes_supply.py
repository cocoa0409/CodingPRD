"""Plant, ProductionRun, and Lot endpoints (PRD SS3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from domain import lazy_lot, touch
from errors import fail
from serializers import ser_lot, ser_plant, ser_run
from store import db
from util import (ALL_ROLES, auth, body, list_response, new_id, ok, req_dt,
                  req_int, req_str, sort_std)

bp = Blueprint("supply", __name__)

RUN_READERS = ("BrandAdmin", "PlantScheduler", "SafetyOfficer")
LOT_READERS = ("BrandAdmin", "DistributorRep", "PlantScheduler", "SafetyOfficer")


def _get_plant(pid):
    p = db["plants"].get(pid)
    if p is None:
        fail("ERR_NOT_FOUND", 404, "plant not found")
    return p


def _get_run(rid):
    r = db["runs"].get(rid)
    if r is None:
        fail("ERR_NOT_FOUND", 404, "production run not found")
    return r


def _get_lot(lid):
    l = db["lots"].get(lid)
    if l is None:
        fail("ERR_NOT_FOUND", 404, "lot not found")
    return l


# ---------------------------------------------------------------------------
# plants
# ---------------------------------------------------------------------------

@bp.post("/api/plants")
def create_plant():
    auth("BrandAdmin")
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    for p in db["plants"].values():
        if p["code"] == code:
            fail("ERR_DUPLICATE_CODE", 409, "plant code already in use")
    now = store.now()
    p = {
        "id": new_id(), "_seq": store.next_seq(), "code": code, "name": name,
        "status": "ACTIVE", "created_at": now, "updated_at": now, "version": 1,
    }
    db["plants"][p["id"]] = p
    return ok(ser_plant(p), 201)


@bp.get("/api/plants/<pid>")
def get_plant(pid):
    auth(*ALL_ROLES)
    return ok(ser_plant(_get_plant(pid)))


# ---------------------------------------------------------------------------
# production runs
# ---------------------------------------------------------------------------

@bp.post("/api/production-runs")
def create_run():
    _, uid = auth("PlantScheduler")
    b = body()
    # entity-backed ownership (SS2.1): X-User-ID is the acting plant
    plant_id = b.get("plant_id")
    if not isinstance(plant_id, str):
        fail("ERR_VALIDATION", 400, "plant_id is required and must be a string")
    if plant_id != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the production run's plant_id")
    line_code = req_str(b, "line_code")
    product_id = req_str(b, "product_id")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    if not window_start < window_end:
        fail("ERR_VALIDATION", 400, "window_start must be strictly before window_end")
    capacity_units = req_int(b, "capacity_units", min_value=1)
    planned_units = req_int(b, "planned_units", min_value=1)
    plant = _get_plant(plant_id)
    if db["products"].get(product_id) is None:
        fail("ERR_NOT_FOUND", 404, "product not found")
    # plant shutdown blocks new scheduling
    if plant["status"] == "SHUTDOWN":
        fail("ERR_INCIDENT_ACTIVE", 422, "plant is SHUTDOWN; scheduling is blocked")
    # half-open window overlap on the same line, ignoring CANCELLED runs;
    # touching windows (new_start == existing_end) are allowed
    for r in db["runs"].values():
        if (r["plant_id"] == plant_id and r["line_code"] == line_code
                and r["status"] != "CANCELLED"):
            if window_start < r["window_end"] and r["window_start"] < window_end:
                fail("ERR_RUN_OVERLAP", 409,
                     "window overlaps another run on the same plant line")
    # capacity: planned may equal capacity but never exceed it
    if planned_units > capacity_units:
        fail("ERR_CAPACITY_EXCEEDED", 422, "planned_units exceeds capacity_units")
    now = store.now()
    r = {
        "id": new_id(), "_seq": store.next_seq(), "plant_id": plant_id,
        "line_code": line_code, "product_id": product_id,
        "window_start": window_start, "window_end": window_end,
        "capacity_units": capacity_units, "planned_units": planned_units,
        "actual_units": None, "waste_units": None, "status": "SCHEDULED",
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["runs"][r["id"]] = r
    return ok(ser_run(r), 201)


@bp.get("/api/production-runs")
def list_runs():
    auth(*RUN_READERS)
    items = sort_std(db["runs"].values())
    plant_id = request.args.get("plant_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if plant_id is not None:
        items = [r for r in items if r["plant_id"] == plant_id]
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response([ser_run(r) for r in items])


@bp.get("/api/production-runs/<rid>")
def get_run(rid):
    auth(*RUN_READERS)
    return ok(ser_run(_get_run(rid)))


@bp.post("/api/production-runs/<rid>/complete")
def complete_run(rid):
    _, uid = auth("PlantScheduler")
    b = body()
    actual_units = req_int(b, "actual_units", min_value=0)
    waste_units = req_int(b, "waste_units", min_value=0)
    r = _get_run(rid)
    # entity-backed ownership: X-User-ID must equal the run's plant
    if r["plant_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the production run's plant_id")
    if r["status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_ALREADY_TERMINAL", 409, "production run is " + r["status"])
    plant = _get_plant(r["plant_id"])
    # no run may be completed at a SHUTDOWN plant
    if plant["status"] == "SHUTDOWN":
        fail("ERR_INCIDENT_ACTIVE", 422, "plant is SHUTDOWN; completion is blocked")
    # capacity binds the outcome twice; equality is allowed in both checks
    if actual_units + waste_units > r["capacity_units"]:
        fail("ERR_CAPACITY_EXCEEDED", 422, "actual_units + waste_units exceeds capacity_units")
    if actual_units < waste_units:
        fail("ERR_CAPACITY_EXCEEDED", 422, "actual_units is less than waste_units")
    if actual_units + waste_units <= 0:
        fail("ERR_CAPACITY_EXCEEDED", 422, "a completion must produce or scrap at least one unit")
    now = store.now()
    r["status"] = "COMPLETED"
    r["actual_units"] = actual_units
    r["waste_units"] = waste_units
    touch(r)
    # exactly one lot is created: net produced units, expiry from completion
    product = db["products"][r["product_id"]]
    lot = {
        "id": new_id(), "_seq": store.next_seq(), "production_run_id": r["id"],
        "product_id": r["product_id"],
        "available_units": actual_units - waste_units,
        "allocated_units": 0, "delivered_units": 0,
        "expires_at": now + timedelta(days=product["shelf_life_unopened_days"]),
        "status": "AVAILABLE", "created_at": now,
    }
    db["lots"][lot["id"]] = lot
    return ok(ser_run(r))


# ---------------------------------------------------------------------------
# lots
# ---------------------------------------------------------------------------

@bp.get("/api/lots")
def list_lots():
    auth(*LOT_READERS)
    items = sort_std(db["lots"].values())
    for l in items:
        lazy_lot(l)
    run_id = request.args.get("production_run_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if run_id is not None:
        items = [l for l in items if l["production_run_id"] == run_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response([ser_lot(l) for l in items])


@bp.get("/api/lots/<lid>")
def get_lot(lid):
    auth(*LOT_READERS)
    return ok(ser_lot(_get_lot(lid)))

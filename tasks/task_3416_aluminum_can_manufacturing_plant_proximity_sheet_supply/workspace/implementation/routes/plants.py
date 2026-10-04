"""Plant endpoints: create, get, and the operations checkpoint (run-ops)."""
from flask import Blueprint

from db import (store, new_id, now_iso, next_seq, touch, parse_ts,
                clock_dt, clock_date_str)
from errors import ApiError, ERR_NOT_FOUND
from middleware import actor, require_role
from response import ok_object
from services.serialize import plant_public
from validation import body_json, req_str, req_int

bp = Blueprint("plants", __name__)


def get_plant_or_404(pid):
    plant = store["plants"].get(pid)
    if plant is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Plant not found.")
    return plant


@bp.post("/plants")
def create_plant():
    _, role = actor()
    require_role(role, ["PlatformAdmin"])
    data = body_json()
    name = req_str(data, "name")
    region = req_str(data, "region")
    capacity = req_int(data, "warehouse_capacity_units", minimum=1)
    ts = now_iso()
    plant = {
        "id": new_id(),
        "name": name,
        "region": region,
        "warehouse_capacity_units": capacity,
        "warehouse_on_hand_units": 0,
        "ops_run_index": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
        "_metal_events": [],
        "_scrap_events": [],
    }
    store["plants"][plant["id"]] = plant
    return ok_object(plant_public(plant), code=201)


@bp.get("/plants/<pid>")
def get_plant(pid):
    actor()
    return ok_object(plant_public(get_plant_or_404(pid)))


@bp.post("/plants/<pid>/run-ops")
def run_ops(pid):
    """Operations checkpoint: bump ops_run_index, then run the two expiry
    sweeps against the logical clock (agreements, then scrap returns)."""
    _, role = actor()
    require_role(role, ["PlantManager"])
    plant = get_plant_or_404(pid)
    plant["ops_run_index"] += 1
    touch(plant)
    today = clock_date_str()
    now_dt = clock_dt()
    for agr in store["agreements"].values():
        if agr["status"] in ("ACTIVE", "RENEGOTIATING") and agr["end_date"] < today:
            agr["status"] = "EXPIRED"
            touch(agr)
    for sr in store["scrap_returns"].values():
        if sr["status"] == "SCHEDULED" and parse_ts(sr["pickup_window_end"]) < now_dt:
            sr["status"] = "EXPIRED"
            touch(sr)
    return ok_object(plant_public(plant))

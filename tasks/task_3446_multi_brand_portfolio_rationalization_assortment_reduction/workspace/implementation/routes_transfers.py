"""Product transfers and their qualification runs."""

from flask import Blueprint, request

import clock
import storage
from calculations import (new_record, bump, capacity_allows, run_result,
                          QUAL_REQUIRED_CONSECUTIVE_PASSES)
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, ALL_ROLES
from serializers import transfer_out, run_out
from validation import body_json, f_str, f_int, f_dt

bp = Blueprint("transfers", __name__, url_prefix="/portfolio")

OPEN_TRANSFER_STATES = ("PLANNED", "QUALIFYING")


@bp.post("/product-transfers")
@synchronized
def create_transfer():
    guard(["SupplyChainPlanner"])
    body = body_json(required=True)
    item_id = f_str(body, "item_id")
    source_plant_id = f_str(body, "source_plant_id")
    target_plant_id = f_str(body, "target_plant_id")
    # step 6: body FKs resolve
    item = storage.items.get(item_id)
    if item is None:
        fail("ERR_NOT_FOUND", f"item {item_id} not found")
    source = storage.plants.get(source_plant_id)
    if source is None:
        fail("ERR_NOT_FOUND", f"plant {source_plant_id} not found")
    target = storage.plants.get(target_plant_id)
    if target is None:
        fail("ERR_NOT_FOUND", f"plant {target_plant_id} not found")
    # step 8: transfer-creation state guards
    if item["item_status"] != "LISTED":
        fail("ERR_ITEM_NOT_TRANSFERABLE", "transfer create requires item LISTED")
    if target["plant_status"] != "OPERATING":
        fail("ERR_TARGET_PLANT_NOT_OPERATING",
             "transfer target plant must be OPERATING")
    # step 11: at most one open transfer per item
    for t in storage.transfers.values():
        if t["item_id"] == item_id and t["transfer_status"] in OPEN_TRANSFER_STATES:
            fail("ERR_TRANSFER_ALREADY_OPEN",
                 "item already has an open product transfer")
    # step 12: structural checks
    if target_plant_id == source_plant_id:
        fail("ERR_SAME_PLANT", "target_plant_id equals source_plant_id")
    if source_plant_id != item["primary_plant_id"]:
        fail("ERR_SOURCE_PLANT_MISMATCH",
             "source_plant_id differs from the item's current primary plant")
    # step 20: capacity gate on the target (pure integer comparison)
    if not capacity_allows(target, item):
        fail("ERR_PLANT_OVER_CAPACITY",
             "projected utilization of the target plant exceeds 110%")
    rec = new_record()
    rec.update({
        "item_id": item_id,
        "source_plant_id": source_plant_id,
        "target_plant_id": target_plant_id,
        "transfer_status": "PLANNED",
        "consecutive_pass_count": 0,
    })
    storage.transfers[rec["id"]] = rec
    return success(transfer_out(rec), status=201)


@bp.get("/product-transfers")
@synchronized
def list_transfers():
    guard(ALL_ROLES)
    records = list(storage.transfers.values())
    for param in ("item_id", "source_plant_id", "target_plant_id", "transfer_status"):
        value = request.args.get(param)
        if value is not None:
            records = [t for t in records if t[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([transfer_out(t) for t in page], response_type="array",
                   pagination=meta)


@bp.get("/product-transfers/<tid>")
@synchronized
def get_transfer(tid):
    guard(ALL_ROLES)
    t = storage.transfers.get(tid)
    if t is None:
        fail("ERR_NOT_FOUND", f"product transfer {tid} not found")
    return success(transfer_out(t))


@bp.post("/product-transfers/<tid>/qualification-runs")
@synchronized
def record_run(tid):
    user_id = guard(["PlantDirector"])
    body = body_json(required=True)
    run_date = f_dt(body, "run_date")
    units_produced = f_int(body, "units_produced", 1)
    units_rejected = f_int(body, "units_rejected", 0)
    # step 5: path id resolves
    transfer = storage.transfers.get(tid)
    if transfer is None:
        fail("ERR_NOT_FOUND", f"product transfer {tid} not found")
    # step 7: runs accepted only while PLANNED or QUALIFYING
    if transfer["transfer_status"] not in OPEN_TRANSFER_STATES:
        fail("ERR_INVALID_STATE",
             "runs require transfer PLANNED or QUALIFYING")
    # step 9: caller must be the PlantDirector of the target plant
    if user_id != transfer["target_plant_id"]:
        fail("ERR_OWNERSHIP_MISMATCH",
             "run certifier's X-User-ID must equal the transfer's target plant")
    # step 15: run payload sanity
    if units_rejected > units_produced:
        fail("ERR_INVALID_RUN", "units_rejected exceeds units_produced")
    result = run_result(units_produced, units_rejected)
    rec = {
        "id": storage.new_id(),
        "created_at": clock.now(),
        "_seq": storage.next_seq(),
        "transfer_id": tid,
        "run_date": run_date,
        "units_produced": units_produced,
        "units_rejected": units_rejected,
        "result": result,
        "certifier_plant_id": user_id,
    }
    storage.runs[rec["id"]] = rec
    # transfer bookkeeping: first run PLANNED -> QUALIFYING; PASS increments
    # the consecutive counter, FAIL resets it; reaching 2 passes auto-executes.
    if transfer["transfer_status"] == "PLANNED":
        transfer["transfer_status"] = "QUALIFYING"
    if result == "PASS":
        transfer["consecutive_pass_count"] += 1
    else:
        transfer["consecutive_pass_count"] = 0
    bump(transfer)
    if transfer["consecutive_pass_count"] >= QUAL_REQUIRED_CONSECUTIVE_PASSES:
        transfer["transfer_status"] = "EXECUTED"
        item = storage.items[transfer["item_id"]]
        item["primary_plant_id"] = transfer["target_plant_id"]
        bump(item)
    return success(run_out(rec), status=201)


@bp.get("/product-transfers/<tid>/qualification-runs")
@synchronized
def list_runs(tid):
    guard(ALL_ROLES)
    if tid not in storage.transfers:
        fail("ERR_NOT_FOUND", f"product transfer {tid} not found")
    records = [r for r in storage.runs.values() if r["transfer_id"] == tid]
    page, meta = paginate(sorted_by_created(records))
    return success([run_out(r) for r in page], response_type="array",
                   pagination=meta)

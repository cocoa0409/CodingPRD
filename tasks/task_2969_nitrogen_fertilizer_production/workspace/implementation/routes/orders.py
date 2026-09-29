"""The order book: two independent state dimensions on one row (PRD 3.5, 3.6)."""
from flask import Blueprint, request

import calc
import cascade
import serialize
import validate as v
from auth import (ALL_ROLES, COMMERCIAL_MANAGER, PROCESS_ENGINEER,
                  SAFETY_OFFICER, actor)
from envelope import list_response, object_response, paging
from errors import ApiError
from guards import duplicate, filtered, load, not_frozen, state
from mutate import touch
from store import db, stamp_new
from util import D, rhu

bp = Blueprint("orders", __name__)
PREFIX = "/nitrogen-ops/production-orders"
ALLOCATION_STATUSES = ("UNALLOCATED", "RESERVED", "CONSUMED", "RELEASED")
SECURITY_STATUSES = ("PENDING", "CLEARED", "DENIED", "EXEMPT")
SECURE_CLASSES = ("CONTROLLED", "HIGH_SECURITY")


def _secure_enough(line, asset):
    if line["regulated"] and asset["security_class"] not in SECURE_CLASSES:
        raise ApiError("ERR_SECURITY_CLASS_INSUFFICIENT")


@bp.post(PREFIX)
def create_order():
    who = actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    run_id = v.s_id(body, "run_id")
    line_id = v.s_id(body, "product_line_id")
    asset_id = v.s_id(body, "destination_asset_id")
    order_code = v.s_code(body, "order_code", 2, 16)
    requested = v.s_num(body, "requested_tons", 3, gt=0)
    run = load("runs", run_id)
    line = load("lines", line_id)
    asset = load("assets", asset_id)
    duplicate("orders", "order_code", order_code)
    _secure_enough(line, asset)
    state(line["product_code"] == asset["product_code"], "ERR_PRODUCT_MISMATCH")
    run_plant = calc.plant_of_run(run)
    state(run_plant is not None and run_plant["id"] == asset["plant_id"],
          "ERR_PRODUCT_MISMATCH",
          "The campaign and the destination asset sit at different plants.")
    row = {
        "run_id": run_id,
        "product_line_id": line_id,
        "destination_asset_id": asset_id,
        "order_code": order_code,
        "requested_tons": requested,
        "reserved_tons": D("0.000"),
        "allocated_ammonia_tons": D("0.000"),
        "produced_tons": None,
        "landed_cost_usd": None,
        "allocation_status": "UNALLOCATED",
        "security_status": "PENDING" if line["regulated"] else "EXEMPT",
        "release_reason": None,
        "created_by_user_id": who["user_id"],
        "security_checked_by_user_id": None,
    }
    stamp_new(row)
    db.orders[row["id"]] = row
    return object_response(serialize.order_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_order(id):
    actor(ALL_ROLES)
    return object_response(serialize.order_json(load("orders", id)))


@bp.get(PREFIX)
def list_orders():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("orders", [
        ("run_id", v.query_str("run_id")),
        ("product_line_id", v.query_str("product_line_id")),
        ("destination_asset_id", v.query_str("destination_asset_id")),
        ("allocation_status", v.query_enum("allocation_status", ALLOCATION_STATUSES)),
        ("security_status", v.query_enum("security_status", SECURITY_STATUSES)),
    ])
    return list_response(serialize.dump("orders", rows), limit, offset)


@bp.post(PREFIX + "/<id>/reserve")
def reserve_order(id):
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    reserve_tons = v.s_num(body, "reserve_tons", 3, gt=0)
    expected = v.s_int(body, "expected_run_version", ge=0)
    order = load("orders", id)
    state(order["allocation_status"] in ("UNALLOCATED", "RELEASED"))
    run = db.runs[order["run_id"]]
    state(run["status"] in ("APPROVED", "RUNNING", "COMPLETED"))
    plant = calc.plant_of_run(run)
    not_frozen(plant)
    state(expected == run["version"], "ERR_STALE_RUN_VERSION")
    line = db.lines[order["product_line_id"]]
    asset = db.assets[order["destination_asset_id"]]
    ammonia = rhu(reserve_tons * line["ammonia_tons_per_product_ton"], 3)
    state(ammonia <= calc.unallocated_ammonia_tons(run), "ERR_AMMONIA_BALANCE_EXCEEDED")
    position = calc.storage_position(asset)
    others = calc.reserved_tons_of_other_orders(asset["id"], order["id"])
    state(position["on_hand_tons"] + others + reserve_tons <= asset["capacity_tons"],
          "ERR_STORAGE_CAPACITY_EXCEEDED")
    order["allocation_status"] = "RESERVED"
    order["reserved_tons"] = reserve_tons
    order["allocated_ammonia_tons"] = ammonia
    order["release_reason"] = None
    touch(order)
    touch(run)
    return object_response(serialize.order_json(order))


@bp.post(PREFIX + "/<id>/release")
def release_order_endpoint(id):
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    reason = v.s_str(body, "release_reason", min_len=1)
    order = load("orders", id)
    state(order["allocation_status"] != "CONSUMED", "ERR_ORDER_ALREADY_PRODUCED")
    state(order["allocation_status"] == "RESERVED")
    cascade.release_order(order, reason)
    return object_response(serialize.order_json(order))


@bp.post(PREFIX + "/<id>/security-check")
def security_check(id):
    who = actor([SAFETY_OFFICER])
    body = v.get_body()
    decision = v.s_enum(body, "decision", ("CLEARED", "DENIED", "PENDING"))
    order = load("orders", id)
    line = db.lines[order["product_line_id"]]
    state(line["regulated"], message="The order's product line is not regulated.")
    if decision in ("CLEARED", "DENIED"):
        state(order["security_status"] == "PENDING")
    else:
        state(order["security_status"] == "DENIED")
    state(who["user_id"] != order["created_by_user_id"], "ERR_SEGREGATION_OF_DUTIES")
    order["security_status"] = decision
    order["security_checked_by_user_id"] = None if decision == "PENDING" else who["user_id"]
    touch(order)
    return object_response(serialize.order_json(order))


@bp.post(PREFIX + "/<id>/produce")
def produce_order(id):
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    produced = v.s_num(body, "produced_tons", 3, gt=0)
    order = load("orders", id)
    state(order["allocation_status"] == "RESERVED")
    run = db.runs[order["run_id"]]
    state(run["status"] == "COMPLETED", "ERR_RUN_NOT_COMPLETED")
    plant = calc.plant_of_run(run)
    not_frozen(plant)
    line = db.lines[order["product_line_id"]]
    asset = db.assets[order["destination_asset_id"]]
    _secure_enough(line, asset)
    state(order["security_status"] in ("CLEARED", "EXEMPT"),
          "ERR_SECURITY_CHECK_NOT_CLEARED")
    state(asset["product_code"] == line["product_code"], "ERR_PRODUCT_MISMATCH")
    position = calc.storage_position(asset)
    state(position["on_hand_tons"] + produced <= asset["capacity_tons"],
          "ERR_STORAGE_CAPACITY_EXCEEDED")
    state(produced <= order["reserved_tons"], "ERR_PRODUCED_EXCEEDS_RESERVED")
    order["produced_tons"] = produced
    order["landed_cost_usd"] = calc.landed_cost(
        produced, line, run["final_unit_cost_usd_per_ton"])
    order["allocation_status"] = "CONSUMED"
    touch(order)
    touch(asset)
    return object_response(serialize.order_json(order))

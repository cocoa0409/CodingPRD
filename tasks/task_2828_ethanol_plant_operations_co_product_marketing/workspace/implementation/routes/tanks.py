"""Product tanks, service holds and denaturant blends."""
from decimal import Decimal

import calc
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from flask import request
from routes import bp
from shape import (enum_param, no_body, page, pagination, require_auth, take)
from store import db, new_row, touch
from util import D, plus_minutes, rhu

TANK_SPEC = {
    "tank_code": {"type": "string", "required": True},
    "product_type": {"type": "enum", "required": True,
                     "values": ["ETHANOL_200_PROOF", "DENATURANT", "DENATURED_E100"]},
    "capacity_gallons": {"type": "dec", "required": True, "gt": 0, "places": 2},
    "opening_gallons": {"type": "dec", "ge": 0, "places": 2, "default": D("0.00")},
    "settling_buffer_minutes": {"type": "int", "ge": 0, "default": 120},
}
HOLD_SPEC = {
    "hold_reason": {"type": "enum", "required": True,
                    "values": ["OFF_SPEC", "MECHANICAL"]},
}
BLEND_SPEC = {
    "blend_code": {"type": "string", "required": True},
    "neat_source_tank_id": {"type": "string", "required": True},
    "denaturant_source_tank_id": {"type": "string", "required": True},
    "destination_tank_id": {"type": "string", "required": True},
    "expected_destination_tank_version": {"type": "int", "required": True, "ge": 1},
    "neat_gallons": {"type": "dec", "required": True, "gt": 0, "places": 2},
    "denaturant_gallons": {"type": "dec", "required": True, "gt": 0, "places": 2},
    "window_start": {"type": "instant", "required": True},
    "window_end": {"type": "instant", "required": True},
}

BATCH_STATUSES = ("CHARGED", "FERMENTING", "HEALTH_WATCH", "DISTILLING",
                  "COMPLETED", "DUMPED")
BLEND_STATUSES = ("SCHEDULED", "EXECUTED", "CANCELLED")
TANK_ROLE_ALIASES = {
    "NEAT_SOURCE": "neat_source_tank_id",
    "NEAT": "neat_source_tank_id",
    "NEAT_SOURCE_TANK": "neat_source_tank_id",
    "DENATURANT_SOURCE": "denaturant_source_tank_id",
    "DENATURANT": "denaturant_source_tank_id",
    "DENATURANT_SOURCE_TANK": "denaturant_source_tank_id",
    "DESTINATION": "destination_tank_id",
    "DEST": "destination_tank_id",
    "DESTINATION_TANK": "destination_tank_id",
}


@bp.route("/product-tanks", methods=["POST"])
def create_tank():
    require_auth(["ProcessOperator"])
    body = take(TANK_SPEC)
    if D(body["opening_gallons"]) > D(body["capacity_gallons"]):
        fail("ERR_VALIDATION", "opening_gallons may not exceed capacity_gallons")
    guards.unique(db.tanks, "tank_code", body["tank_code"])
    tank = new_row({
        "tank_code": body["tank_code"],
        "product_type": body["product_type"],
        "capacity_gallons": rhu(body["capacity_gallons"], 2),
        "opening_gallons": rhu(body["opening_gallons"], 2),
        "settling_buffer_minutes": body["settling_buffer_minutes"],
        "service_status": "IN_SERVICE",
        "hold_reason": None,
        "held_at": None,
    })
    db.tanks[tank["id"]] = tank
    return ok(serialize.tank_out(tank), 201)


@bp.route("/product-tanks/<tank_id>", methods=["GET"])
def get_tank(tank_id):
    require_auth(["PlantManager", "ProcessOperator", "LogisticsCoordinator",
                  "ComplianceOfficer"])
    tank = guards.get_tank(tank_id)
    return ok(serialize.tank_out(tank))


@bp.route("/product-tanks/<tank_id>/batches", methods=["GET"])
def list_tank_batches(tank_id):
    require_auth(["PlantManager", "ProcessOperator"])
    status = enum_param("status", BATCH_STATUSES)
    limit, offset = pagination()
    tank = guards.get_tank(tank_id)
    rows = [b for b in db.batches.values()
            if b["destination_tank_id"] == tank["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.batch_out(r) for r in window], limit, offset, len(rows))


@bp.route("/product-tanks/<tank_id>/denaturant-blends", methods=["GET"])
def list_tank_blends(tank_id):
    require_auth(["PlantManager", "ProcessOperator"])
    status = enum_param("status", BLEND_STATUSES)
    raw_role = request.args.get("tank_role")
    role_field = None
    if raw_role is not None and raw_role != "":
        role_field = TANK_ROLE_ALIASES.get(str(raw_role).strip().upper())
        if role_field is None:
            fail("ERR_VALIDATION", "tank_role is not a recognised blend role")
    limit, offset = pagination()
    tank = guards.get_tank(tank_id)
    rows = []
    for blend in db.blends.values():
        if role_field is not None:
            if blend[role_field] != tank["id"]:
                continue
        elif tank["id"] not in (blend["neat_source_tank_id"],
                                blend["denaturant_source_tank_id"],
                                blend["destination_tank_id"]):
            continue
        rows.append(blend)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["window_start"], r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.blend_out(r) for r in window], limit, offset, len(rows))


@bp.route("/product-tanks/<tank_id>/hold", methods=["POST"])
def hold_tank(tank_id):
    require_auth(["ProcessOperator"])
    body = take(HOLD_SPEC)
    tank = guards.get_tank(tank_id)
    if tank["service_status"] != "IN_SERVICE":
        fail("ERR_INVALID_TANK_STATE",
             "Tank is %s and may not be held" % tank["service_status"])
    reason = body["hold_reason"]
    tank["hold_reason"] = reason
    tank["held_at"] = db.clock
    if reason == "OFF_SPEC":
        tank["service_status"] = "ON_HOLD"
        for shipment in db.shipments.values():
            if (shipment["source_tank_id"] == tank["id"]
                    and shipment["loading_status"] == "SCHEDULED"):
                shipment["loading_status"] = "BLOCKED"
                touch(shipment)
    else:
        tank["service_status"] = "OUT_OF_SERVICE"
        for blend in db.blends.values():
            if blend["status"] != "SCHEDULED":
                continue
            if tank["id"] not in (blend["neat_source_tank_id"],
                                  blend["denaturant_source_tank_id"],
                                  blend["destination_tank_id"]):
                continue
            blend["status"] = "CANCELLED"
            blend["cancelled_at"] = db.clock
            touch(blend)
        for shipment in db.shipments.values():
            if (shipment["source_tank_id"] == tank["id"]
                    and shipment["loading_status"] == "SCHEDULED"):
                shipment["loading_status"] = "CANCELLED"
                shipment["billing_status"] = "VOIDED"
                shipment["cancelled_at"] = db.clock
                touch(shipment)
                track = db.tracks.get(shipment["track_id"])
                if track is not None:
                    touch(track)
    touch(tank)
    return ok(serialize.tank_out(tank))


@bp.route("/product-tanks/<tank_id>/release", methods=["POST"])
def release_tank(tank_id):
    require_auth(["ProcessOperator"])
    no_body()
    tank = guards.get_tank(tank_id)
    if tank["service_status"] not in ("ON_HOLD", "OUT_OF_SERVICE"):
        fail("ERR_INVALID_TANK_STATE",
             "Tank is %s and has no hold to release" % tank["service_status"])
    tank["service_status"] = "IN_SERVICE"
    tank["hold_reason"] = None
    tank["held_at"] = None
    for shipment in db.shipments.values():
        if (shipment["source_tank_id"] == tank["id"]
                and shipment["loading_status"] == "BLOCKED"):
            shipment["loading_status"] = "SCHEDULED"
            touch(shipment)
    touch(tank)
    return ok(serialize.tank_out(tank))


@bp.route("/denaturant-blends", methods=["POST"])
def create_blend():
    require_auth(["ProcessOperator"])
    body = take(BLEND_SPEC)
    if body["window_end"] <= body["window_start"]:
        fail("ERR_VALIDATION", "window_end must be strictly after window_start")
    destination = guards.get_tank(body["destination_tank_id"])
    neat = guards.get_tank(body["neat_source_tank_id"])
    denaturant = guards.get_tank(body["denaturant_source_tank_id"])
    guards.unique(db.blends, "blend_code", body["blend_code"])
    if body["expected_destination_tank_version"] != destination["version"]:
        fail("ERR_STALE_TANK_VERSION",
             "Destination tank %s is at version %d"
             % (destination["tank_code"], destination["version"]))
    guards.require_product_type(neat, "ETHANOL_200_PROOF")
    guards.require_product_type(denaturant, "DENATURANT")
    guards.require_product_type(destination, "DENATURED_E100")
    occupancy_end = plus_minutes(body["window_end"],
                                 destination["settling_buffer_minutes"])
    clash = guards.blend_conflicts(destination, body["window_start"], occupancy_end)
    if clash is not None:
        fail("ERR_TANK_OCCUPANCY_CONFLICT",
             "Destination tank %s is reserved by blend %s through that window"
             % (destination["tank_code"], clash["blend_code"]))
    blend = new_row({
        "blend_code": body["blend_code"],
        "neat_source_tank_id": neat["id"],
        "denaturant_source_tank_id": denaturant["id"],
        "destination_tank_id": destination["id"],
        "expected_destination_tank_version": body["expected_destination_tank_version"],
        "neat_gallons": rhu(body["neat_gallons"], 2),
        "denaturant_gallons": rhu(body["denaturant_gallons"], 2),
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "occupancy_end": occupancy_end,
        "status": "SCHEDULED",
        "output_gallons": None,
        "denaturant_pct": None,
        "executed_at": None,
        "cancelled_at": None,
    })
    db.blends[blend["id"]] = blend
    touch(destination)
    return ok(serialize.blend_out(blend), 201)


@bp.route("/denaturant-blends/<blend_id>", methods=["GET"])
def get_blend(blend_id):
    require_auth(["PlantManager", "ProcessOperator", "LogisticsCoordinator"])
    blend = guards.get_blend(blend_id)
    return ok(serialize.blend_out(blend))


@bp.route("/denaturant-blends/<blend_id>/execute", methods=["POST"])
def execute_blend(blend_id):
    require_auth(["ProcessOperator"])
    no_body()
    blend = guards.get_blend(blend_id)
    if blend["status"] != "SCHEDULED":
        fail("ERR_INVALID_BLEND_STATE",
             "Blend is %s and may not be executed" % blend["status"])
    neat = db.tanks[blend["neat_source_tank_id"]]
    denaturant = db.tanks[blend["denaturant_source_tank_id"]]
    destination = db.tanks[blend["destination_tank_id"]]
    guards.require_tank_in_service(neat)
    guards.require_tank_in_service(denaturant)
    guards.require_tank_in_service(destination)
    output, pct, in_spec = calc.denaturant_spec(blend["neat_gallons"],
                                                blend["denaturant_gallons"])
    if not in_spec:
        fail("ERR_DENATURANT_SPEC_VIOLATION",
             "denaturant_pct %s is outside the finished-product band"
             % format(pct, "f"))
    if derive.tank_current_gallons(neat) < D(blend["neat_gallons"]):
        fail("ERR_INSUFFICIENT_TANK_VOLUME",
             "Tank %s holds less than %s gallons of neat ethanol"
             % (neat["tank_code"], format(D(blend["neat_gallons"]), "f")))
    if derive.tank_current_gallons(denaturant) < D(blend["denaturant_gallons"]):
        fail("ERR_INSUFFICIENT_TANK_VOLUME",
             "Tank %s holds less than %s gallons of denaturant"
             % (denaturant["tank_code"],
                format(D(blend["denaturant_gallons"]), "f")))
    if derive.tank_available_gallons(destination) < output:
        fail("ERR_INSUFFICIENT_TANK_CAPACITY",
             "Tank %s cannot receive %s gallons"
             % (destination["tank_code"], format(output, "f")))
    blend["status"] = "EXECUTED"
    blend["output_gallons"] = output
    blend["denaturant_pct"] = pct
    blend["executed_at"] = db.clock
    touch(blend)
    touch(neat)
    touch(denaturant)
    touch(destination)
    return ok(serialize.blend_out(blend))

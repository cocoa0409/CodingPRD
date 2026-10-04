"""Vehicle endpoints (PRD sections 3.5, 3.6, 3.9)."""

from flask import Blueprint, request

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, check_occ, body, req_field, as_str,
                  as_int, as_num, as_enum, parse_dt, find, ok, ok_list)

bp = Blueprint("vehicles", __name__)

_VEHICLE_GET_ROLES = {"PlatformAdmin", "FleetManager", "ServiceDispatcher",
                      "ServiceTechnician", "ReleaseManager", "ProductionPlanner",
                      "TelematicsIngestion"}
_VEHICLE_LIST_ROLES = {"PlatformAdmin", "FleetManager", "ServiceDispatcher",
                       "ServiceTechnician", "ReleaseManager", "ProductionPlanner"}


def recompute_hold_count(order):
    """Derived-field reconciliation: count of the order's held vehicles."""
    hc = sum(1 for v in DB.vehicles.values()
             if v["vehicle_order_id"] == order["id"] and v["software_hold"])
    if hc != order["hold_count"]:
        order["hold_count"] = hc
        store.touch(order)


@bp.post("/evfleet/vehicles")
def create_vehicle():
    _, role = auth()
    require_role(role, {"ProductionPlanner"})
    b = body()
    vehicle_order_id = as_str(req_field(b, "vehicle_order_id"), "vehicle_order_id")
    battery_module_id = as_str(req_field(b, "battery_module_id"), "battery_module_id")
    # priority 3: body FK existence
    order = find(DB.orders, vehicle_order_id, "vehicle order")
    module = find(DB.modules, battery_module_id, "battery module")
    # priority 5: OCC on VehicleOrder.version
    expected = as_int(req_field(b, "expected_vehicle_order_version"),
                      "expected_vehicle_order_version")
    check_occ(expected, order["version"])
    # priority 6: state preconditions — registration acts on CONFIRMED/IN_PRODUCTION
    if order["status"] in ("FULFILLED", "CANCELLED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "vehicle order is in terminal state %s" % order["status"])
    if order["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "vehicle order in %s does not accept VIN registrations"
                       % order["status"])
    # priority 10: vin globally unique
    vin = as_str(req_field(b, "vin"), "vin")
    if any(v["vin"] == vin for v in DB.vehicles.values()):
        raise ApiError(E.ERR_DUPLICATE_VIN, 409, "vin %s already exists" % vin)
    # priority 13: cross-entity references
    if module["pack_kwh"] != order["battery_pack_kwh"]:
        raise ApiError(E.ERR_MODULE_PACK_MISMATCH, 422,
                       "module pack_kwh differs from the order's battery_pack_kwh")
    if module["quality_status"] != "PASSED":
        raise ApiError(E.ERR_MODULE_NOT_PASSED, 409,
                       "battery module is not PASSED")
    # priority 14: weekly ramp capacity
    if not calc.ramp_has_capacity():
        raise ApiError(E.ERR_RAMP_CAPACITY_EXCEEDED, 422,
                       "weekly ramp capacity for the current ISO week is exhausted")
    v = {
        "vehicle_order_id": vehicle_order_id,
        "battery_module_id": battery_module_id,
        "vin": vin,
        "delivery_status": "ASSEMBLED",
        "telematics_status": "OFFLINE",
        "software_version": "1.0.0",
        "software_hold": False,
        "current_soh_pct": 100.0,
        "battery_eol_status": "NONE",
        "eol_valuation_refurbish_cents": None,
        "eol_valuation_recovery_cents": None,
        "last_battery_report_at": None,
    }
    store.stamp_new(v)
    DB.vehicles[v["id"]] = v
    # cascade: module PASSED -> ALLOCATED
    module["quality_status"] = "ALLOCATED"
    store.touch(module)
    # cascade: order counters, auto-transitions, version bump
    order["registered_count"] += 1
    if order["status"] == "CONFIRMED":
        order["status"] = "IN_PRODUCTION"
    if order["registered_count"] == order["quantity"]:
        order["status"] = "FULFILLED"
    store.touch(order)
    return ok(store.public(v), 201)


@bp.get("/evfleet/vehicles/<vid>")
def get_vehicle(vid):
    _, role = auth()
    require_role(role, _VEHICLE_GET_ROLES)
    e = find(DB.vehicles, vid, "vehicle")
    return ok(store.public(e), 200)


@bp.get("/evfleet/vehicles")
def list_vehicles():
    _, role = auth()
    require_role(role, _VEHICLE_LIST_ROLES)
    items = list(DB.vehicles.values())
    vo = request.args.get("vehicle_order_id")
    if vo is not None:
        items = [v for v in items if v["vehicle_order_id"] == vo]
    bm = request.args.get("battery_module_id")
    if bm is not None:
        items = [v for v in items if v["battery_module_id"] == bm]
    return ok_list(items)


@bp.post("/evfleet/vehicles/<vid>/transition")
def transition_vehicle(vid):
    _, role = auth()
    require_role(role, {"ServiceDispatcher"})
    v = find(DB.vehicles, vid, "vehicle")
    b = body()
    dimension = as_enum(req_field(b, "dimension"), {"DELIVERY", "TELEMATICS"},
                        "dimension")
    to_state = as_str(req_field(b, "to_state"), "to_state")
    # priority 6: state preconditions on the addressed dimension
    if dimension == "DELIVERY":
        st = v["delivery_status"]
        if to_state == "IN_TRANSIT":
            if st != "ASSEMBLED":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "IN_TRANSIT is offered from ASSEMBLED")
        elif to_state == "AT_DEPOT":
            if st != "IN_TRANSIT":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "AT_DEPOT is offered from IN_TRANSIT")
        elif to_state == "COMMISSIONED":
            if st != "AT_DEPOT":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "COMMISSIONED is offered from AT_DEPOT")
            if v["software_hold"]:
                raise ApiError(E.ERR_SOFTWARE_HOLD, 409,
                               "delivery advance blocked by software_hold")
            if v["telematics_status"] != "ACTIVE":
                raise ApiError(E.ERR_TELEMATICS_NOT_ACTIVE, 409,
                               "commissioning requires telematics ACTIVE")
        else:
            raise ApiError(E.ERR_VALIDATION, 400,
                           "unknown DELIVERY to_state %r" % to_state)
    else:  # TELEMATICS
        st = v["telematics_status"]
        if to_state == "PROVISIONED":
            if st != "OFFLINE":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "PROVISIONED is offered from OFFLINE")
        elif to_state == "ACTIVE":
            if st not in ("PROVISIONED", "SUSPENDED"):
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "ACTIVE is offered from PROVISIONED or SUSPENDED")
        elif to_state == "SUSPENDED":
            if st != "ACTIVE":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "SUSPENDED is offered from ACTIVE")
        else:
            raise ApiError(E.ERR_VALIDATION, 400,
                           "unknown TELEMATICS to_state %r" % to_state)
    # priority 14: charging demand gate at commissioning
    if dimension == "DELIVERY" and to_state == "COMMISSIONED":
        order = DB.orders[v["vehicle_order_id"]]
        if order["requires_depot_charging"]:
            if not calc.charging_gate_pass(order["depot_id"]):
                raise ApiError(E.ERR_CHARGING_CAPACITY_INSUFFICIENT, 422,
                               "commissioned charging capacity at the depot is "
                               "insufficient for the in-service fleet plus this van")
    # apply
    if dimension == "DELIVERY":
        v["delivery_status"] = to_state
    else:
        v["telematics_status"] = to_state
    store.touch(v)
    # every vehicle mutation recomputes the parent order's hold_count
    recompute_hold_count(DB.orders[v["vehicle_order_id"]])
    return ok(store.public(v), 200)


@bp.post("/evfleet/vehicles/<vid>/battery-health")
def report_battery_health(vid):
    _, role = auth()
    require_role(role, {"TelematicsIngestion"})
    v = find(DB.vehicles, vid, "vehicle")
    # priority 13: telematics must be ACTIVE
    if v["telematics_status"] != "ACTIVE":
        raise ApiError(E.ERR_TELEMATICS_NOT_ACTIVE, 409,
                       "battery reports require telematics ACTIVE")
    b = body()
    measured_soh_pct = as_num(req_field(b, "measured_soh_pct"), "measured_soh_pct")
    measured_at = as_str(req_field(b, "measured_at"), "measured_at")
    parse_dt(measured_at, "measured_at")
    v["current_soh_pct"] = measured_soh_pct
    v["last_battery_report_at"] = measured_at
    if calc.D(measured_soh_pct) < calc.SOH_EOL_THRESHOLD \
            and v["battery_eol_status"] == "NONE":
        # sticky EOL_REVIEW entry: both valuation variants computed now
        v["battery_eol_status"] = "EOL_REVIEW"
        module = DB.modules[v["battery_module_id"]]
        refurbish, recovery = calc.eol_valuations(measured_soh_pct,
                                                  module["pack_kwh"])
        v["eol_valuation_refurbish_cents"] = refurbish
        v["eol_valuation_recovery_cents"] = recovery
    store.touch(v)
    return ok(store.public(v), 200)

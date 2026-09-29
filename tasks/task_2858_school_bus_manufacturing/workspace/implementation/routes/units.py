"""Bus units: minting, build advance, certification, waiver, dealer hand-off."""

from flask import Blueprint

import shapes
from db import (by_creation, db, get_or_404, make_record, now_iso, public,
                touch, values)
from errors import ApiError
from middleware import (COMPLIANCE_OFFICER, CONTRACTS_ADMIN, DEALER_AGENT,
                        PLANT_SCHEDULER, actor)
from response import created, list_response, object_response, q_enum, q_str
from services import calc, domain

bp = Blueprint("units", __name__)

PRODUCTION_STATUSES = ("PLANNED", "SLOTTED", "BODY_JOINED", "BUILT", "DELIVERED")
CERTIFICATION_STATUSES = ("PENDING", "CERTIFIED", "NONCONFORMING", "WAIVED")
SERVICE_STATUSES = ("NONE", "RECALL_OPEN", "RECALL_CLOSED")
ADVANCE_TARGETS = ("BODY_JOINED", "BUILT")


def new_unit_record(fields):
    unit = make_record(fields)
    db.units[unit["id"]] = unit
    return unit


# -------------------------------------------------------- minting from an order

@bp.post("/contract-orders/<order_id>/units")
def mint_unit(order_id):
    actor(PLANT_SCHEDULER)
    data = shapes.body()
    vin = shapes.get_str(data, "vin")

    order = get_or_404(db.orders, order_id, "ERR_CONTRACT_ORDER_NOT_FOUND")
    if order["status"] != "ACTIVE":
        raise ApiError("ERR_ORDER_NOT_ACTIVE")

    bid = db.bids[order["bid_id"]]
    model = db.models[bid["bus_model_id"]]
    package = db.packages[bid["propulsion_package_id"]]
    profile = db.profiles[order["spec_profile_id"]]

    nominal, derated = calc.range_validation(package, profile)
    joint = calc.joint_strength_kn(model, order["awarded_rollover_reinforcement"])

    if not calc.dec(derated) >= calc.dec(profile["required_route_range_mi"]):
        raise ApiError("ERR_ROUTE_RANGE_INSUFFICIENT")
    if not calc.dec(joint) >= calc.dec(profile["min_joint_strength_kn"]):
        raise ApiError("ERR_JOINT_STRENGTH_INSUFFICIENT")
    if profile["status"] != "PUBLISHED":
        raise ApiError("ERR_SPEC_PROFILE_NOT_PUBLISHED")
    if domain.vin_exists(vin):
        raise ApiError("ERR_VIN_ALREADY_EXISTS")
    if len(domain.units_of_order(order["id"])) >= int(order["unit_count"]):
        raise ApiError("ERR_ORDER_UNIT_COUNT_EXCEEDED")

    unit = new_unit_record({
        "contract_order_id": order["id"],
        "bus_model_id": model["id"],
        "propulsion_package_id": package["id"],
        "spec_profile_id": profile["id"],
        "dealer_id": None,
        "vin": vin,
        "seat_capacity": order["awarded_seat_capacity"],
        "emergency_exit_count": order["awarded_emergency_exit_count"],
        "mirror_config": order["awarded_mirror_config"],
        "lap_shoulder_belts": order["awarded_lap_shoulder_belts"],
        "eight_lamp_system": order["awarded_eight_lamp_system"],
        "crossing_arm": order["awarded_crossing_arm"],
        "rollover_reinforcement": order["awarded_rollover_reinforcement"],
        "joint_strength_kn": joint,
        "registration_state_code": profile["state_code"],
        "nominal_range_mi": nominal,
        "derated_route_range_mi": derated,
        "production_status": "PLANNED",
        "certification_status": "PENDING",
        "service_status": "NONE",
        "driver_training_status": "PENDING",
        "certified_at": None,
        "delivered_at": None,
        "waiver_justification": None,
        "is_legacy_import": False,
    })
    domain.recompute_order(order)
    return created(public(unit))


# ---------------------------------------------------------------- retrieval

@bp.get("/bus-units")
def list_units():
    actor()
    order_id = q_str("contract_order_id")
    model_id = q_str("bus_model_id")
    package_id = q_str("propulsion_package_id")
    profile_id = q_str("spec_profile_id")
    dealer_id = q_str("dealer_id")
    production = q_enum("production_status", PRODUCTION_STATUSES)
    certification = q_enum("certification_status", CERTIFICATION_STATUSES)
    service = q_enum("service_status", SERVICE_STATUSES)
    rows = []
    for unit in values(db.units):
        if order_id is not None and unit["contract_order_id"] != order_id:
            continue
        if model_id is not None and unit["bus_model_id"] != model_id:
            continue
        if package_id is not None and unit["propulsion_package_id"] != package_id:
            continue
        if profile_id is not None and unit["spec_profile_id"] != profile_id:
            continue
        if dealer_id is not None and unit["dealer_id"] != dealer_id:
            continue
        if production is not None and unit["production_status"] != production:
            continue
        if certification is not None and unit["certification_status"] != certification:
            continue
        if service is not None and unit["service_status"] != service:
            continue
        rows.append(unit)
    return list_response(by_creation(rows))


@bp.get("/bus-units/<unit_id>")
def read_unit(unit_id):
    actor()
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")
    return object_response(public(unit))


# ------------------------------------------------------------- build advance

@bp.post("/bus-units/<unit_id>/advance-build")
def advance_build(unit_id):
    actor(PLANT_SCHEDULER)
    data = shapes.body()
    to_status = shapes.get_enum(data, "to_status", ADVANCE_TARGETS)
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")

    if to_status == "BODY_JOINED":
        from_status, slot_from, slot_to = "SLOTTED", "COMMITTED", "IN_PROGRESS"
    else:
        from_status, slot_from, slot_to = "BODY_JOINED", "IN_PROGRESS", "COMPLETED"

    if unit["production_status"] != from_status:
        raise ApiError("ERR_UNIT_PHASE_INVALID")
    slot = None
    for candidate in by_creation(domain.slots_of_unit(unit["id"])):
        if candidate["status"] == slot_from:
            slot = candidate
            break
    if slot is None:
        raise ApiError("ERR_UNIT_PHASE_INVALID",
                       "The bus has no build slot in %s." % slot_from)

    unit["production_status"] = to_status
    touch(unit)
    slot["status"] = slot_to
    touch(slot)
    domain.recompute_order(domain.order_of_unit(unit))
    return object_response(public(unit))


# --------------------------------------------------------------- certifying

@bp.post("/bus-units/<unit_id>/certify")
def certify_unit(unit_id):
    user_id, _role = actor(COMPLIANCE_OFFICER)
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")
    if unit["production_status"] != "BUILT":
        raise ApiError("ERR_UNIT_PHASE_INVALID")
    if unit["certification_status"] == "CERTIFIED":
        raise ApiError("ERR_UNIT_PHASE_INVALID", "The bus is already certified.")

    profile = db.profiles[unit["spec_profile_id"]]
    if not calc.dec(unit["derated_route_range_mi"]) >= calc.dec(
            profile["required_route_range_mi"]):
        raise ApiError("ERR_ROUTE_RANGE_INSUFFICIENT")
    if not calc.dec(unit["joint_strength_kn"]) >= calc.dec(profile["min_joint_strength_kn"]):
        raise ApiError("ERR_JOINT_STRENGTH_INSUFFICIENT")

    tests = domain.tests_of_unit(unit["id"])
    passed = [t for t in tests if t["status"] == "PASSED"]
    if unit["certification_status"] != "WAIVED":
        passed_types = set(t["test_type"] for t in passed)
        for required in calc.required_test_types(profile):
            if required not in passed_types:
                raise ApiError("ERR_REQUIRED_TEST_MISSING",
                               "No passed %s test on file." % required)
    if any(t["status"] == "FAILED" for t in tests):
        raise ApiError("ERR_OPEN_TEST_FAILURE")
    if any(t["recorded_by_user_id"] == user_id for t in passed):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if profile["status"] != "PUBLISHED":
        raise ApiError("ERR_SPEC_PROFILE_NOT_PUBLISHED")

    unit["certification_status"] = "CERTIFIED"
    unit["certified_at"] = now_iso()
    touch(unit)
    domain.recompute_order(domain.order_of_unit(unit))
    return object_response(public(unit))


@bp.post("/bus-units/<unit_id>/waive-nonconformance")
def waive_unit(unit_id):
    actor(COMPLIANCE_OFFICER)
    data = shapes.body()
    justification = shapes.get_str(data, "waiver_justification")
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")

    failed = [t for t in domain.tests_of_unit(unit["id"]) if t["status"] == "FAILED"]
    if unit["certification_status"] != "NONCONFORMING":
        raise ApiError("ERR_WAIVER_NOT_PERMITTED", "The bus is not nonconforming.")
    if not failed:
        raise ApiError("ERR_WAIVER_NOT_PERMITTED", "The bus has no failed test to waive.")
    if any(t["test_type"] in ("BRAKE", "ROLLOVER") for t in failed):
        raise ApiError("ERR_WAIVER_NOT_PERMITTED",
                       "Brake and rollover failures may never be waived.")

    unit["waiver_justification"] = justification
    for test in by_creation(failed):
        test["status"] = "VOIDED"
        touch(test)
    unit["certification_status"] = "WAIVED"
    touch(unit)
    domain.recompute_order(domain.order_of_unit(unit))
    return object_response(public(unit))


# ------------------------------------------------------- dealer hand-off

@bp.post("/bus-units/<unit_id>/assign-dealer")
def assign_dealer(unit_id):
    actor(CONTRACTS_ADMIN)
    data = shapes.body()
    dealer_id = shapes.get_str(data, "dealer_id")
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")
    dealer = get_or_404(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")
    if dealer["certification_standing"] != "GOOD":
        raise ApiError("ERR_DEALER_STANDING_RESTRICTED")
    if unit["registration_state_code"] not in dealer["licensed_state_codes"]:
        raise ApiError("ERR_DEALER_NOT_LICENSED_IN_STATE")
    unit["dealer_id"] = dealer["id"]
    touch(unit)
    return object_response(public(unit))


@bp.post("/bus-units/<unit_id>/complete-driver-training")
def complete_driver_training(unit_id):
    user_id, _role = actor(DEALER_AGENT)
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")
    if unit["dealer_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_DEALER")
    unit["driver_training_status"] = "COMPLETED"
    touch(unit)
    return object_response(public(unit))


@bp.post("/bus-units/<unit_id>/deliver")
def deliver_unit(unit_id):
    user_id, role = actor(CONTRACTS_ADMIN, DEALER_AGENT)
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")
    if role == DEALER_AGENT and unit["dealer_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_DEALER")
    if unit["production_status"] != "BUILT":
        raise ApiError("ERR_UNIT_PHASE_INVALID")
    if unit["certification_status"] not in ("CERTIFIED", "WAIVED"):
        raise ApiError("ERR_UNIT_NOT_CERTIFIED")
    if unit["driver_training_status"] != "COMPLETED":
        raise ApiError("ERR_DRIVER_TRAINING_INCOMPLETE")

    unit["production_status"] = "DELIVERED"
    unit["delivered_at"] = now_iso()
    touch(unit)
    if unit["dealer_id"]:
        domain.recompute_dealer(db.dealers.get(unit["dealer_id"]))
    domain.recompute_order(domain.order_of_unit(unit))
    return object_response(public(unit))

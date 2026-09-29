"""Unit staging, assembly, serialisation and shipment (PRD 3.7)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from services import calc
from services.core import resolve, restrict_model_if_released, rows

bp = Blueprint("units", __name__)

BUILD_STATUSES = ("COMPONENTS_STAGED", "ASSEMBLED", "LABELED", "SHIPPED", "HELD", "SCRAPPED")
LABEL_STATUSES = ("NONE", "APPLIED", "INVALID")
CHANNELS = ("TRADE", "RETAIL", "BUILDER")

READ_ROLES = [
    "PlantOperator",
    "QualityInspector",
    "PlantAdmin",
    "WarrantyAnalyst",
    "ComplianceEngineer",
]


def referenced_lots(unit):
    """The component lots a unit draws from, in created_at ascending order."""
    ids = [unit.get("gas_control_lot_id"), unit.get("safety_valve_lot_id")]
    lots = [db.db.component_lots[i] for i in ids if i is not None]
    return ordered(lots)


def _settle_lots(lots):
    """Recompute each lot's piece ledger and settle the CONSUMED transition."""
    for lot in lots:
        remaining = lot["quantity"] - serializers.consumed_quantity(lot["id"])
        if remaining <= 0 and lot["status"] == "RELEASED":
            lot["status"] = "CONSUMED"
        touch(lot)


@bp.post("/heater-units")
@endpoint(["PlantOperator"])
def stage_unit():
    body = validation.json_body()
    tank_lot_id = validation.string(body, "tank_lot_id")
    safety_valve_lot_id = validation.string(body, "safety_valve_lot_id")
    gas_control_lot_id = validation.string(body, "gas_control_lot_id", required=False)
    # product_model_id is never taken from the client; it is inherited below.

    # Position 5: body foreign keys, left to right.
    tank_lot = resolve("tank_lot", tank_lot_id)
    safety_valve_lot = resolve("component_lot", safety_valve_lot_id)
    gas_control_lot = None
    if gas_control_lot_id is not None:
        gas_control_lot = resolve("component_lot", gas_control_lot_id)

    model = db.db.models[tank_lot["product_model_id"]]

    # Position 14: component families must match the slots they fill.
    if gas_control_lot is not None and gas_control_lot["category"] != "GAS_VALVE":
        raise ApiError("ERR_COMPONENT_CATEGORY_MISMATCH")
    if safety_valve_lot["category"] != "TP_RELIEF_VALVE":
        raise ApiError("ERR_COMPONENT_CATEGORY_MISMATCH")

    # Position 15: gas-control applicability.
    if model["fuel_type"] == "GAS":
        if gas_control_lot is None:
            raise ApiError("ERR_GAS_CONTROL_REQUIRED")
    elif gas_control_lot is not None:
        raise ApiError("ERR_GAS_CONTROL_NOT_APPLICABLE")

    # Position 37: the tank lot's good output caps the unit population.
    drawn = sum(
        1
        for u in rows("unit")
        if u["tank_lot_id"] == tank_lot["id"] and u["build_status"] != "SCRAPPED"
    )
    if drawn >= tank_lot["good_quantity"]:
        raise ApiError("ERR_LOT_UNIT_CAPACITY_EXCEEDED")

    row = make_row(
        {
            "tank_lot_id": tank_lot["id"],
            "product_model_id": model["id"],
            "gas_control_lot_id": gas_control_lot["id"] if gas_control_lot else None,
            "safety_valve_lot_id": safety_valve_lot["id"],
            "serial_number": None,
            "build_status": "COMPONENTS_STAGED",
            "held_from_status": None,
            "label_status": "NONE",
            "production_period": tank_lot["production_period"],
            "install_water_hardness_gpg": None,
            "water_hardness_band": None,
            "hardness_factor": None,
            "shipped_at": None,
            "hold_reason_code": None,
        }
    )
    db.db.units[row["id"]] = row
    return response.created(serializers.heater_unit(row))


@bp.get("/heater-units/<uid>")
@endpoint(READ_ROLES)
def read_unit(uid):
    return response.ok(serializers.heater_unit(resolve("unit", uid)))


@bp.get("/heater-units")
@endpoint(READ_ROLES)
def list_units():
    tank_lot_id = validation.query_string("tank_lot_id")
    product_model_id = validation.query_string("product_model_id")
    gas_control_lot_id = validation.query_string("gas_control_lot_id")
    safety_valve_lot_id = validation.query_string("safety_valve_lot_id")
    build_status = validation.query_enum("build_status", BUILD_STATUSES)
    production_period = validation.query_string("production_period")
    serial_number = validation.query_string("serial_number")

    result = rows("unit")
    if tank_lot_id is not None:
        result = [r for r in result if r["tank_lot_id"] == tank_lot_id]
    if product_model_id is not None:
        result = [r for r in result if r["product_model_id"] == product_model_id]
    if gas_control_lot_id is not None:
        result = [r for r in result if r.get("gas_control_lot_id") == gas_control_lot_id]
    if safety_valve_lot_id is not None:
        result = [r for r in result if r.get("safety_valve_lot_id") == safety_valve_lot_id]
    if build_status is not None:
        result = [r for r in result if r["build_status"] == build_status]
    if production_period is not None:
        result = [r for r in result if r["production_period"] == production_period]
    if serial_number is not None:
        result = [r for r in result if r.get("serial_number") == serial_number]
    return response.paginate(ordered(result), serializers.heater_unit)


@bp.post("/heater-units/<uid>/assemble")
@endpoint(["PlantOperator"])
def assemble_unit(uid):
    unit = resolve("unit", uid)
    if unit["build_status"] != "COMPONENTS_STAGED":
        raise ApiError("ERR_INVALID_UNIT_STATE")
    tank_lot = db.db.tank_lots[unit["tank_lot_id"]]
    if tank_lot["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")

    lots = referenced_lots(unit)
    # Position 11: availability and supplier standing.
    for lot in lots:
        if lot["status"] != "RELEASED":
            raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
        if lot["quantity"] - serializers.consumed_quantity(lot["id"]) < 1:
            raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
        supplier = db.db.suppliers[lot["supplier_id"]]
        if supplier["qualification_status"] not in ("QUALIFIED", "CONDITIONAL"):
            raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
    # Position 27: qualification currency, checked only once standing is good.
    now = db.db.now()
    for lot in lots:
        supplier = db.db.suppliers[lot["supplier_id"]]
        qualified_until = supplier.get("qualified_until")
        if qualified_until is None or qualified_until < now:
            raise ApiError("ERR_QUALIFICATION_EXPIRED")

    unit["build_status"] = "ASSEMBLED"
    touch(unit)
    _settle_lots(lots)
    return response.ok(serializers.heater_unit(unit))


@bp.post("/heater-units/<uid>/label")
@endpoint(["PlantOperator"])
def label_unit(uid):
    unit = resolve("unit", uid)
    if unit["build_status"] != "ASSEMBLED":
        raise ApiError("ERR_INVALID_UNIT_STATE")
    model = db.db.models[unit["product_model_id"]]
    # The only moment the two catalogue dimensions are read together.
    if model["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_MODEL_NOT_CERTIFIED")
    if model["release_status"] != "RELEASED":
        raise ApiError("ERR_MODEL_NOT_RELEASED")

    already = sum(
        1
        for u in rows("unit")
        if u["product_model_id"] == model["id"]
        and u["production_period"] == unit["production_period"]
        and u.get("serial_number") is not None
    )
    unit["serial_number"] = calc.serial_number(
        model["label_serial_prefix"], unit["production_period"], already + 1
    )
    unit["build_status"] = "LABELED"
    unit["label_status"] = "APPLIED"
    touch(unit)
    return response.ok(serializers.heater_unit(unit))


@bp.post("/heater-units/<uid>/ship")
@endpoint(["PlantOperator"])
def ship_unit(uid):
    unit = resolve("unit", uid)
    body = validation.json_body()
    hardness = validation.number(body, "install_water_hardness_gpg")
    channel = validation.enum(body, "distribution_channel", CHANNELS)

    if unit["build_status"] != "LABELED" or unit["label_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_UNIT_STATE")
    model = db.db.models[unit["product_model_id"]]
    if model["release_status"] != "RELEASED":
        raise ApiError("ERR_MODEL_NOT_RELEASED")
    if channel != model["channel"]:
        raise ApiError("ERR_MODEL_NOT_RELEASED")

    band = calc.hardness_band(hardness)
    unit["build_status"] = "SHIPPED"
    unit["shipped_at"] = db.db.now()
    unit["install_water_hardness_gpg"] = hardness
    unit["water_hardness_band"] = band
    unit["hardness_factor"] = calc.HARDNESS_FACTOR[band]
    touch(unit)

    # Shipment is the accrual event for the model's warranty reserve.
    model["warranty_reserve_accrued_cents"] += calc.WARRANTY_ACCRUAL_CENTS_PER_UNIT[
        model["fuel_type"]
    ]
    touch(model)
    return response.ok(serializers.heater_unit(unit))


@bp.post("/heater-units/<uid>/release-hold")
@endpoint(["PlantOperator"])
def release_hold(uid):
    unit = resolve("unit", uid)
    if unit["build_status"] != "HELD":
        raise ApiError("ERR_INVALID_UNIT_STATE")
    model = db.db.models[unit["product_model_id"]]
    target = unit.get("held_from_status")

    if target == "LABELED":
        # The component lots are deliberately not re-examined on this branch.
        if unit["label_status"] != "APPLIED":
            raise ApiError("ERR_INVALID_UNIT_STATE")
        if model["certification_status"] == "DECERTIFIED":
            raise ApiError("ERR_MODEL_NOT_CERTIFIED")
        restored = "LABELED"
    elif target == "ASSEMBLED":
        for lot in referenced_lots(unit):
            if lot["status"] != "RELEASED":
                raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
        if model["certification_status"] == "DECERTIFIED":
            raise ApiError("ERR_MODEL_NOT_CERTIFIED")
        restored = "ASSEMBLED"
    else:
        for lot in referenced_lots(unit):
            if lot["status"] != "RELEASED":
                raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
        restored = "COMPONENTS_STAGED"

    unit["build_status"] = restored
    unit["held_from_status"] = None
    unit["hold_reason_code"] = None
    touch(unit)
    # The model recomputes held_unit_count; a restriction is never self-healed.
    touch(model)
    return response.ok(serializers.heater_unit(unit))


@bp.post("/heater-units/<uid>/disassemble")
@endpoint(["PlantOperator"])
def disassemble_unit(uid):
    unit = resolve("unit", uid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")

    if unit["build_status"] not in ("COMPONENTS_STAGED", "ASSEMBLED", "HELD"):
        raise ApiError("ERR_INVALID_UNIT_STATE")

    was_held = unit["build_status"] == "HELD"
    lots = referenced_lots(unit)
    unit["build_status"] = "SCRAPPED"
    unit["hold_reason_code"] = reason_code
    touch(unit)
    # COMPENSATION: the drawn pieces return, but a CONSUMED lot is not resurrected.
    _settle_lots(lots)
    if was_held:
        model = db.db.models[unit["product_model_id"]]
        restrict_model_if_released(model)
        touch(model)
    return response.ok(serializers.heater_unit(unit))

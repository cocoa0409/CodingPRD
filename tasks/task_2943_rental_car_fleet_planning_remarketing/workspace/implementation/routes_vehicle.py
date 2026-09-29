"""Vehicle minting, in-fleeting entry, usage posting and the computed reads."""

from flask import Blueprint

import calc
import cascade
import serialize
import validate
from auth import ALL_ROLES, NON_OPERATOR_ROLES, authorize, require_scope
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, store, touch

bp = Blueprint("vehicle", __name__)

VIN_LENGTH = 16


@bp.route("/fleet/purchase-allocations/<allocation_id>/vehicles", methods=["POST"])
def mint_vehicle(allocation_id):
    authorize(("FleetPlanner",))
    allocation = validate.load("allocation", allocation_id)
    payload = validate.body()

    vin = validate.s_str(payload, "vin", exact_len=VIN_LENGTH)
    validate.s_id(payload, "current_market_id")
    market = validate.load("market", payload["current_market_id"])

    if any(v["vin"] == vin for v in store.vehicles.values()):
        raise ApiError("ERR_DUPLICATE_VIN", "A vehicle with vin '%s' already exists." % vin)

    if allocation["status"] not in ("ORDERED", "PARTIALLY_INFLEETED"):
        raise ApiError(
            "ERR_ALLOCATION_NOT_CANCELLABLE",
            "Vehicles may only be minted against an ORDERED or PARTIALLY_INFLEETED "
            "allocation.",
        )

    if len(calc.vehicles_of_allocation(allocation["id"])) >= allocation["unit_count"]:
        raise ApiError(
            "ERR_ALLOCATION_UNIT_LIMIT_REACHED",
            "The allocation's unit_count ceiling has already been reached.",
        )

    row = base_row()
    row.update({
        "allocation_id": allocation["id"],
        "segment_id": allocation["segment_id"],
        "program_id": allocation["program_id"],
        "current_market_id": market["id"],
        "vin": vin,
        "capitalized_cost_cents": allocation["capitalized_cost_per_unit_cents"],
        "fleet_status": "ON_ORDER",
        "condition_status": "SOUND",
        "odometer_km": 0,
        "rented_days_total": 0,
        "available_days_total": 0,
        "revenue_to_date_cents": 0,
        "registered_at": None,
        "licensed_at": None,
        "prep_completed_at": None,
        "first_rent_ready_at": None,
        "in_service_at": None,
        "held_for_sale_at": None,
        "net_book_value_at_hold_cents": None,
    })
    store.vehicles[row["id"]] = row
    cascade.post_ledger(
        row["id"],
        "CAPITALIZATION",
        row["capitalized_cost_cents"],
        "Vehicle",
        row["id"],
        "capitalization of vehicle %s at purchase" % vin,
    )
    return created(serialize.vehicle(row))


@bp.route("/fleet/vehicles/<vehicle_id>", methods=["GET"])
def read_vehicle(vehicle_id):
    authorize(ALL_ROLES)
    return ok(serialize.vehicle(validate.load("vehicle", vehicle_id)))


@bp.route("/fleet/vehicles", methods=["GET"])
def list_vehicles():
    authorize(ALL_ROLES)
    return collect(
        store.vehicles.values(),
        [
            ("allocation_id", "allocation_id", "str"),
            ("segment_id", "segment_id", "str"),
            ("program_id", "program_id", "str"),
            ("current_market_id", "current_market_id", "str"),
            ("fleet_status", "fleet_status", "str"),
            ("condition_status", "condition_status", "str"),
            ("vin", "vin", "str"),
        ],
        serialize.vehicle,
    )


@bp.route("/fleet/vehicles/<vehicle_id>/in-fleet", methods=["POST"])
def in_fleet_vehicle(vehicle_id):
    actor, _role = authorize(("MarketOperator",))
    vehicle = validate.load("vehicle", vehicle_id)
    require_scope(actor, vehicle["current_market_id"])

    if vehicle["fleet_status"] != "ON_ORDER":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "Only an ON_ORDER vehicle may enter the in-fleeting pipeline.",
        )
    allocation = store.allocations.get(vehicle["allocation_id"])
    if allocation is not None and allocation["status"] not in (
        "ORDERED",
        "PARTIALLY_INFLEETED",
    ):
        raise ApiError(
            "ERR_ALLOCATION_NOT_CANCELLABLE",
            "The vehicle's allocation is not ORDERED or PARTIALLY_INFLEETED.",
        )
    plan = None
    if allocation is not None:
        plan = store.plans.get(allocation["plan_id"])
    if plan is not None and plan["status"] != "LOCKED":
        raise ApiError(
            "ERR_PLAN_NOT_LOCKED",
            "The grandparent fleet plan must be LOCKED before in-fleeting.",
        )
    market = store.markets.get(vehicle["current_market_id"])
    if market is not None and market["status"] != "ACTIVE":
        raise ApiError("ERR_MARKET_SUSPENDED", "The vehicle's market is SUSPENDED.")

    vehicle["fleet_status"] = "IN_FLEETING"
    touch(vehicle)
    return ok(serialize.vehicle(vehicle))


@bp.route("/fleet/vehicles/<vehicle_id>/usage", methods=["POST"])
def post_usage(vehicle_id):
    actor, _role = authorize(("MarketOperator",))
    vehicle = validate.load("vehicle", vehicle_id)
    require_scope(actor, vehicle["current_market_id"])
    payload = validate.body()

    odometer = validate.s_int(payload, "odometer_km", ge=0)
    rented_delta = validate.s_int(payload, "rented_days_delta", ge=0)
    available_delta = validate.s_int(payload, "available_days_delta", ge=0)
    revenue_delta = validate.s_int(payload, "revenue_cents_delta", ge=0)

    if vehicle["fleet_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "Usage may only be posted onto an IN_SERVICE vehicle.",
        )
    if odometer < vehicle["odometer_km"]:
        raise ApiError(
            "ERR_ODOMETER_REGRESSION",
            "The submitted odometer_km is below the vehicle's stored reading.",
        )

    vehicle["odometer_km"] = odometer
    vehicle["rented_days_total"] += rented_delta
    vehicle["available_days_total"] += available_delta
    vehicle["revenue_to_date_cents"] += revenue_delta
    touch(vehicle)
    return ok(serialize.vehicle(vehicle))


@bp.route("/fleet/vehicles/<vehicle_id>/valuation", methods=["GET"])
def read_valuation(vehicle_id):
    authorize(ALL_ROLES)
    vehicle = validate.load("vehicle", vehicle_id)
    return ok(calc.valuation(vehicle))


@bp.route("/fleet/vehicles/<vehicle_id>/channel-recommendation", methods=["GET"])
def read_channel_recommendation(vehicle_id):
    authorize(NON_OPERATOR_ROLES)
    vehicle = validate.load("vehicle", vehicle_id)
    return ok(calc.channel_recommendation(vehicle))


@bp.route("/fleet/vehicles/<vehicle_id>/ledger-entries", methods=["GET"])
def list_vehicle_ledger(vehicle_id):
    authorize(ALL_ROLES)
    vehicle = validate.load("vehicle", vehicle_id)
    return collect(
        calc.ledger_of_vehicle(vehicle["id"]),
        [
            ("entry_type", "entry_type", "str"),
            ("source_entity_type", "source_entity_type", "str"),
        ],
        serialize.ledger_entry,
        sort_keys=("posted_at", "created_at"),
    )

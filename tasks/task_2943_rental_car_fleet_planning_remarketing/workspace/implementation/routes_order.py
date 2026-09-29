"""Inter-city redistribution orders: the cyclic two-man workflow (PRD 3.6)."""

from flask import Blueprint

import calc
import cascade
import serialize
import validate
from auth import ALL_ROLES, authorize, require_scope
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, parse_instant, store, touch

bp = Blueprint("order", __name__)

NON_TERMINAL = calc.NON_TERMINAL_ORDER_STATUSES


@bp.route("/fleet/redistribution-orders", methods=["POST"])
def draft_order():
    authorize(("FleetPlanner",))
    payload = validate.body()

    vehicle = validate.body_fk(payload, "vehicle_id", "vehicle")
    destination = validate.body_fk(payload, "destination_market_id", "market")

    validate.s_id(payload, "vehicle_id")
    validate.s_id(payload, "destination_market_id")
    distance_km = validate.s_int(payload, "distance_km", gt=0)
    depart_raw, depart_dt = validate.s_instant(payload, "planned_depart_at")
    receive_raw, receive_dt = validate.s_instant(payload, "planned_receive_at")

    if vehicle["fleet_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "Only an IN_SERVICE vehicle may be redistributed.",
        )

    if depart_dt >= receive_dt:
        raise ApiError(
            "ERR_TRANSFER_WINDOW_INVALID",
            "planned_depart_at must fall strictly before planned_receive_at.",
        )

    for other in calc.orders_of_vehicle(vehicle["id"]):
        if other["status"] not in NON_TERMINAL:
            continue
        other_start = parse_instant(other["planned_depart_at"])
        other_end = parse_instant(other["planned_receive_at"])
        if other_start is None or other_end is None:
            continue
        # half-open [depart, receive): back-to-back hauls are legal
        if depart_dt < other_end and other_start < receive_dt:
            raise ApiError(
                "ERR_VEHICLE_TRANSFER_OVERLAP",
                "The proposed window overlaps another open haul for this vehicle.",
            )

    if destination["id"] == vehicle["current_market_id"]:
        raise ApiError(
            "ERR_SAME_MARKET_TRANSFER",
            "destination_market_id must differ from the vehicle's current market.",
        )

    origin = store.markets[vehicle["current_market_id"]]
    segment = store.segments[vehicle["segment_id"]]
    estimated = calc.transport_cost(distance_km, origin)
    if estimated > calc.payback_ceiling_cents(segment):
        raise ApiError(
            "ERR_TRANSPORT_COST_EXCEEDS_BENEFIT",
            "The estimated transport cost exceeds the 45-day rental payback ceiling.",
        )

    row = base_row()
    row.update({
        "vehicle_id": vehicle["id"],
        "origin_market_id": origin["id"],
        "destination_market_id": destination["id"],
        "distance_km": distance_km,
        "planned_depart_at": depart_raw,
        "planned_receive_at": receive_raw,
        "proposed_by_user_id": None,
        "authorized_by_user_id": None,
        "revision_count": 0,
        "rejection_reason": None,
        "estimated_transport_cost_cents": estimated,
        "actual_transport_cost_cents": None,
        "depart_at": None,
        "receive_at": None,
        "status": "DRAFT",
    })
    store.orders[row["id"]] = row
    return created(serialize.order(row))


@bp.route("/fleet/redistribution-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    authorize(ALL_ROLES)
    return ok(serialize.order(validate.load("order", order_id)))


@bp.route("/fleet/redistribution-orders", methods=["GET"])
def list_orders():
    authorize(ALL_ROLES)
    return collect(
        store.orders.values(),
        [
            ("vehicle_id", "vehicle_id", "str"),
            ("origin_market_id", "origin_market_id", "str"),
            ("destination_market_id", "destination_market_id", "str"),
            ("status", "status", "str"),
        ],
        serialize.order,
    )


@bp.route("/fleet/redistribution-orders/<order_id>/propose", methods=["POST"])
def propose_order(order_id):
    actor, _role = authorize(("FleetPlanner",))
    order = validate.load("order", order_id)
    vehicle = store.vehicles[order["vehicle_id"]]

    if order["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Only a DRAFT or REJECTED order may be proposed.",
        )
    was_rejected = order["status"] == "REJECTED"
    if was_rejected and order["revision_count"] >= calc.MAX_REVISIONS:
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "The order has already been revised three times.",
        )
    if vehicle["fleet_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "The order's vehicle is no longer IN_SERVICE.",
        )

    if was_rejected:
        order["revision_count"] += 1
        order["rejection_reason"] = None
    order["proposed_by_user_id"] = actor
    order["status"] = "PROPOSED"
    touch(order)
    return ok(serialize.order(order))


@bp.route("/fleet/redistribution-orders/<order_id>/reject", methods=["POST"])
def reject_order(order_id):
    authorize(("FleetController",))
    order = validate.load("order", order_id)
    payload = validate.body()
    reason = validate.s_str(payload, "rejection_reason")

    if order["status"] != "PROPOSED":
        raise ApiError("ERR_ORDER_INVALID_STATE", "Only a PROPOSED order may be rejected.")

    order["status"] = "REJECTED"
    order["rejection_reason"] = reason
    touch(order)
    return ok(serialize.order(order))


@bp.route("/fleet/redistribution-orders/<order_id>/authorize", methods=["POST"])
def authorize_order(order_id):
    actor, _role = authorize(("FleetController",))
    order = validate.load("order", order_id)

    if order["status"] != "PROPOSED":
        raise ApiError("ERR_ORDER_INVALID_STATE", "Only a PROPOSED order may be authorized.")
    if actor == order["proposed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The authorizing operator must differ from proposed_by_user_id.",
        )
    destination = store.markets.get(order["destination_market_id"])
    if destination is not None and destination["status"] != "ACTIVE":
        raise ApiError("ERR_MARKET_SUSPENDED", "The destination market is SUSPENDED.")

    order["authorized_by_user_id"] = actor
    order["status"] = "AUTHORIZED"
    touch(order)
    return ok(serialize.order(order))


@bp.route("/fleet/redistribution-orders/<order_id>/depart", methods=["POST"])
def depart_order(order_id):
    actor, _role = authorize(("MarketOperator",))
    order = validate.load("order", order_id)
    require_scope(actor, order["origin_market_id"])
    vehicle = store.vehicles[order["vehicle_id"]]

    if order["status"] != "AUTHORIZED":
        raise ApiError("ERR_ORDER_INVALID_STATE", "Only an AUTHORIZED order may depart.")
    if vehicle["fleet_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "The order's vehicle is not IN_SERVICE.",
        )
    destination = store.markets.get(order["destination_market_id"])
    if destination is not None and destination["status"] != "ACTIVE":
        raise ApiError("ERR_MARKET_SUSPENDED", "The destination market is SUSPENDED.")

    order["status"] = "IN_TRANSIT"
    order["depart_at"] = store.now_iso()
    touch(order)
    vehicle["fleet_status"] = "IN_TRANSIT"
    touch(vehicle)
    return ok(serialize.order(order))


@bp.route("/fleet/redistribution-orders/<order_id>/receive", methods=["POST"])
def receive_order(order_id):
    actor, _role = authorize(("MarketOperator",))
    order = validate.load("order", order_id)
    require_scope(actor, order["destination_market_id"])
    vehicle = store.vehicles[order["vehicle_id"]]
    payload = validate.body()

    actual_cost = validate.s_int(payload, "actual_transport_cost_cents", ge=0)
    odometer = validate.s_int(payload, "odometer_km", ge=0)

    if order["status"] != "IN_TRANSIT":
        raise ApiError("ERR_ORDER_INVALID_STATE", "Only an IN_TRANSIT order may be received.")
    if vehicle["fleet_status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "The order's vehicle is not IN_TRANSIT.",
        )
    if odometer < vehicle["odometer_km"]:
        raise ApiError(
            "ERR_ODOMETER_REGRESSION",
            "The submitted odometer_km is below the vehicle's stored reading.",
        )

    order["status"] = "RECEIVED"
    order["receive_at"] = store.now_iso()
    order["actual_transport_cost_cents"] = actual_cost
    touch(order)

    vehicle["current_market_id"] = order["destination_market_id"]
    vehicle["odometer_km"] = odometer
    vehicle["fleet_status"] = "IN_SERVICE"
    touch(vehicle)

    cascade.post_ledger(
        vehicle["id"],
        "TRANSPORT_COST",
        actual_cost,
        "RedistributionOrder",
        order["id"],
        "invoiced line haul for redistribution order",
    )
    return ok(serialize.order(order))


@bp.route("/fleet/redistribution-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    authorize(("FleetController",))
    order = validate.load("order", order_id)
    vehicle = store.vehicles[order["vehicle_id"]]

    if order["status"] not in NON_TERMINAL:
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "A RECEIVED or CANCELLED order cannot be cancelled.",
        )
    was_in_transit = order["status"] == "IN_TRANSIT"
    if was_in_transit and vehicle["fleet_status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "The order's vehicle is not IN_TRANSIT.",
        )

    order["status"] = "CANCELLED"
    touch(order)
    if was_in_transit:
        # current_market_id stays at the origin: the haul was recalled.
        vehicle["fleet_status"] = "IN_SERVICE"
        touch(vehicle)
    return ok(serialize.order(order))

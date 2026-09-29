"""Distribution orders: submission, allocation waterfall, shipment and cancellation."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate

bp = Blueprint("orders", __name__)

ORDER_STATES = ("SUBMITTED", "ALLOCATED", "SHIPPED", "REJECTED", "CANCELLED")
CHANNELS = ("SELF_DISTRIBUTED", "WHOLESALER")


@bp.get("/distribution-orders")
def list_orders():
    authenticate(ALL_ROLES)
    beer_id = validation.query_string("beer_id")
    state_license_id = validation.query_string("state_license_id")
    appointment_id = validation.query_string("appointment_id")
    state = validation.query_enum("state", ORDER_STATES)
    channel = validation.query_enum("channel", CHANNELS)

    def predicate(row):
        return (helpers.matches(row, "beer_id", beer_id)
                and helpers.matches(row, "state_license_id", state_license_id)
                and helpers.matches(row, "appointment_id", appointment_id)
                and helpers.matches(row, "state", state)
                and helpers.matches(row, "channel", channel))

    rows, limit, offset, total = helpers.listing("orders", derive.serialize_order, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/distribution-orders/<order_id>")
def read_order(order_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_order(helpers.find("orders", order_id)))


@bp.post("/distribution-orders")
def create_order():
    authenticate(["BreweryAdmin"])
    payload = validation.body()
    beer_id = validation.field_id(payload, "beer_id")
    state_license_id = validation.field_id(payload, "state_license_id")
    order_code = validation.field_string(payload, "order_code", 1, 24)
    bbl_requested = validation.field_number(payload, "bbl_requested", 2, exclusive_minimum=0)
    ship_to_state_code = validation.field_state_code(payload, "ship_to_state_code")
    distance_miles = validation.field_int(payload, "distance_miles", minimum=0)
    requested_ship = validation.field_datetime(payload, "requested_ship_utc")

    helpers.brewery()
    beer = helpers.find("beers", beer_id)
    licence = helpers.find("licenses", state_license_id)
    helpers.unique("orders", order_code)
    helpers.require_notice_active()
    cascades.refresh_license_expiry(licence)
    helpers.license_active_guard(licence)
    helpers.beer_formula_guard(beer)
    helpers.beer_label_guard(beer)
    helpers.license_window_guard(licence)
    if ship_to_state_code != licence.get("state_code"):
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")

    appointment = derive.live_appointment_for(state_license_id, beer_id)
    if appointment is not None:
        channel = "WHOLESALER"
        appointment_id = appointment["id"]
    else:
        channel = "SELF_DISTRIBUTED"
        appointment_id = None
        if licence.get("license_type") == "WHOLESALER_ONLY":
            raise ApiError("ERR_WHOLESALER_APPOINTMENT_REQUIRED")

    money = calc.landed_cost(bbl_requested, beer["price_per_bbl_cents"],
                             distance_miles, channel)
    row = store.new_row({
        "beer_id": beer_id,
        "state_license_id": state_license_id,
        "appointment_id": appointment_id,
        "order_code": order_code,
        "bbl_requested": calc.bbl2(bbl_requested),
        "ship_to_state_code": ship_to_state_code,
        "distance_miles": distance_miles,
        "requested_ship_utc": requested_ship,
        "channel": channel,
        "product_cents": money["product_cents"],
        "freight_cents": money["freight_cents"],
        "franchise_fee_cents": money["franchise_fee_cents"],
        "landed_cost_cents": money["landed_cost_cents"],
        "state": "SUBMITTED",
        "allocated_bbl": calc.bbl(0),
        "allocation_lines": [],
        "rejection_reason": None,
        "cancel_reason": None,
        "shipped_at_utc": None,
    })
    helpers.insert("orders", row)
    return envelope.object_response(derive.serialize_order(row), 201)


@bp.post("/distribution-orders/<order_id>/allocate")
def allocate_order(order_id):
    authenticate(["BreweryAdmin"])
    validation.body()
    order = helpers.find("orders", order_id)
    if order.get("state") != "SUBMITTED":
        raise ApiError("ERR_ORDER_TRANSITION_INVALID")
    helpers.require_notice_active()
    licence = helpers.find("licenses", order["state_license_id"])
    cascades.refresh_license_expiry(licence)
    helpers.license_active_guard(licence)
    helpers.license_window_guard(licence)

    seen = set()
    candidates = []
    for run in derive.rows("runs"):
        if run.get("state") != "COMPLETED" or run.get("destination") != "DISTRIBUTION":
            continue
        batch = derive.batch_of_run(run)
        if batch is None or batch.get("beer_id") != order["beer_id"]:
            continue
        available = derive.run_available_bbl(run)
        if available <= 0:
            continue
        candidates.append((run, available))

    candidates.sort(key=lambda pair: (pair[0].get("removed_at_utc"),
                                      pair[0].get("created_at") or "",
                                      pair[0].get("_seq") or 0))

    pool = sum((Decimal(available) for _run, available in candidates), Decimal("0"))
    requested = Decimal(order["bbl_requested"])
    if pool < requested:
        order["state"] = "REJECTED"
        order["rejection_reason"] = "INSUFFICIENT_INVENTORY"
        cascades.touch_once(order, seen)
        return envelope.object_response(derive.serialize_order(order))

    remaining = requested
    lines = []
    for run, available in candidates:
        if remaining <= 0:
            break
        take = min(Decimal(available), remaining)
        lines.append({"packaging_run_id": run["id"], "bbl": calc.bbl(take)})
        remaining = calc.bbl(remaining - take)
        cascades.touch_once(run, seen)

    order["allocation_lines"] = lines
    order["allocated_bbl"] = calc.bbl(requested)
    order["state"] = "ALLOCATED"
    cascades.touch_once(order, seen)
    return envelope.object_response(derive.serialize_order(order))


@bp.post("/distribution-orders/<order_id>/ship")
def ship_order(order_id):
    authenticate(["BreweryAdmin"])
    validation.body()
    order = helpers.find("orders", order_id)
    if order.get("state") != "ALLOCATED":
        raise ApiError("ERR_ORDER_NOT_ALLOCATED")
    helpers.require_notice_active()
    licence = helpers.find("licenses", order["state_license_id"])
    cascades.refresh_license_expiry(licence)
    helpers.license_active_guard(licence)
    helpers.license_window_guard(licence)

    allocated = Decimal(order.get("allocated_bbl") or 0)
    if order.get("channel") == "SELF_DISTRIBUTED":
        projected = calc.bbl(Decimal(derive.barrels_shipped_ytd(licence)) + allocated)
        if projected > Decimal(licence["annual_barrel_cap"]):
            raise ApiError("ERR_SELF_DISTRIBUTION_CAP_EXCEEDED")

    seen = set()
    order["state"] = "SHIPPED"
    order["shipped_at_utc"] = helpers.now()
    cascades.touch_once(order, seen)
    for line in order.get("allocation_lines") or []:
        run = store.DB["runs"].get(line.get("packaging_run_id"))
        if run is not None:
            cascades.touch_once(run, seen)
    cascades.touch_once(licence, seen)
    return envelope.object_response(derive.serialize_order(order))


@bp.post("/distribution-orders/<order_id>/cancel")
def cancel_order(order_id):
    authenticate(["BreweryAdmin"])
    payload = validation.body()
    reason = validation.field_string(payload, "reason", 1, None)
    order = helpers.find("orders", order_id)
    state = order.get("state")
    if state not in ("SUBMITTED", "ALLOCATED"):
        raise ApiError("ERR_ORDER_TRANSITION_INVALID")

    seen = set()
    order["state"] = "CANCELLED"
    order["cancel_reason"] = reason
    if state == "ALLOCATED":
        cascades.release_allocation(order, seen)
    cascades.touch_once(order, seen)
    return envelope.object_response(derive.serialize_order(order))

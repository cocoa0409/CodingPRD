"""Fulfillment orders and royalty accruals endpoints.

Request-shape checks (the highest-precedence rung of the validation ladder),
authentication, role authorization and existence checks all live here; the
workflow rules they delegate to live in the service modules.
"""
from flask import request

from decimal import Decimal

import db
from errors import (
    ERR_ALREADY_COMMITTED, ERR_CAPACITY_EXCEEDED, ERR_COUNTERFEIT_OVERCOUNT,
    ERR_DESIGN_NOT_APPROVED, ERR_DESIGN_NOT_FOUND, ERR_EVENT_WINDOW_CLOSED,
    ERR_FORBIDDEN_ROLE, ERR_FULFILLMENT_ORDER_NOT_FOUND, ERR_GUARANTEE_FLOOR_BREACH,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVENTORY_INSUFFICIENT,
    ERR_LICENSOR_MISMATCH, ERR_LICENSOR_NOT_FOUND, ERR_LICENSOR_PROJECT_NOT_FOUND,
    ERR_LISTING_UNVERIFIED, ERR_LOT_EXHAUSTED, ERR_NO_ACCRUED_ROYALTY, ERR_NOT_FOUND,
    ERR_PICK_REMARK_REUSED, ERR_PRINT_QUANTITY_EXCEEDED, ERR_PRINT_TYPECAST_MISMATCH,
    ERR_PRODUCTION_ALREADY_COMMITTED, ERR_PRODUCTION_ORDER_NOT_FOUND,
    ERR_RUSH_COMMITMENT_BREACH, ERR_SEGREGATION_OF_DUTIES, ERR_SETTLEMENT_NOOP,
    ERR_STALE_VERSION, ERR_UNAUTHENTICATED, ERR_UNBALANCED_ALLOCATION, fail)
from response import (authenticate, ok_array, ok_object, paginate, pagination,
                      require_roles)
from routing import (
    CAPACITY_TYPES, CARRIERS, CHANNELS, DECISIONS, DEFAULT_HOURS_TO_OUTCOME,
    DESTROY_MODES, DISTRESS_REASONS, EVENT_OUTCOMES, EVENT_WINDOW_HOURS,
    GARMENT_SKUS, PRINT_TYPES, RETIRE_REASONS, TRIGGER_TYPES,
    api, body, check_licensor_ownership, check_licensor_project, check_segregation,
    get_capacity, get_design, get_layer, get_licensor, get_order, get_report, get_run,
    licensor_projects, optional_string, require_enum, require_field, require_int,
    require_instant, require_number, require_order_version, require_version)
from services import fulfillment, ledger, pricing, production



@api.route("/fulfillment-orders", methods=["POST"])
def create_fulfillment_order():
    payload = body()
    production_order_id = require_field(payload, "production_order_id")
    channel = require_enum(payload, "channel", CHANNELS)
    destination_code = require_field(payload, "destination_code")
    if not isinstance(destination_code, str) or not destination_code.strip():
        fail(ERR_INVALID_REQUEST, "field 'destination_code' must be a non-empty string")
    quantity = require_int(payload, "quantity", positive=True)
    rush_flag = payload.get("rush_flag", False)
    if rush_flag is not None and not isinstance(rush_flag, bool):
        fail(ERR_INVALID_REQUEST, "field 'rush_flag' must be a boolean")
    donation_recipient_code = optional_string(payload, "donation_recipient_code", None)
    pick_remark = optional_string(payload, "pick_remark", None)

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    run = get_run(production_order_id)
    if run.get("status") == "PARALLEL_HOLD":
        fail(ERR_INVALID_STATE,
             "demand is placed against a committed outcome, not a held possibility")

    order = {
        "production_order_id": production_order_id,
        "channel": channel,
        "destination_code": destination_code,
        "quantity": quantity,
        "rush_flag": bool(rush_flag),
        "status": "PLANNED",
        "picked_qty": 0,
        "shipped_qty": 0,
        "returned_qty": 0,
        "destroyed_qty": 0,
        "donated_qty": 0,
        "requested_wholesale_cents": pricing.quote_wholesale(
            channel, quantity, bool(rush_flag), donation_recipient_code),
        "realized_wholesale_cents": 0,
        "write_down_inventory_cents": 0,
        "distress_reason": None,
        "donation_recipient_code": donation_recipient_code,
        "pick_remark": pick_remark,
    }
    db.init_common(order)
    db.store.fulfillment_orders[order["id"]] = order
    return ok_object(order, 201)


@api.route("/fulfillment-orders", methods=["GET"])
def list_fulfillment_orders():
    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator", "AuditOnly"))
    limit, offset = pagination()
    items = db.created_order(list(db.store.fulfillment_orders.values()))
    for arg, field in (("production_order_id", "production_order_id"),
                       ("status", "status"), ("channel", "channel")):
        value = request.args.get(arg)
        if value:
            items = [o for o in items if o.get(field) == value]
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/fulfillment-orders/<fulfillment_order_id>", methods=["GET"])
def read_fulfillment_order(fulfillment_order_id):
    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator", "AuditOnly"))
    return ok_object(get_order(fulfillment_order_id))


@api.route("/fulfillment-orders/<fulfillment_order_id>/pick", methods=["POST"])
def pick_fulfillment_order(fulfillment_order_id):
    payload = body()
    quantity = require_int(payload, "quantity", positive=True)
    if "pick_remark" not in payload or payload.get("pick_remark") is None:
        fail(ERR_INVALID_REQUEST, "field 'pick_remark' is required")
    pick_remark = payload["pick_remark"]
    if not isinstance(pick_remark, str) or not pick_remark.strip():
        fail(ERR_INVALID_REQUEST, "field 'pick_remark' must be a non-empty string")

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    order = get_order(fulfillment_order_id)
    run = get_run(order.get("production_order_id"))
    # State eligibility is the fifth rung and optimistic concurrency the sixth, so
    # an action on a locked-down order is refused before any version is compared
    # (PRD 2.6, 2.10).
    if order.get("status") not in ("PLANNED", "PICKED"):
        fail(ERR_INVALID_STATE,
             "fulfillment order is not in a state that permits a pick")
    expected = require_order_version(payload, run)
    production.refresh_printed_totals(run)
    fulfillment.pick(order, run, quantity, pick_remark, expected,
                     db.store.designs.get(run.get("design_id")))
    return ok_object(order, 200)


@api.route("/fulfillment-orders/<fulfillment_order_id>/ship", methods=["POST"])
def ship_fulfillment_order(fulfillment_order_id):
    payload = body()
    quantity = require_int(payload, "quantity", positive=True)
    carrier = require_enum(payload, "carrier", CARRIERS)
    sla_hours = require_int(payload, "sla_hours", positive=True)

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    order = get_order(fulfillment_order_id)
    run = get_run(order.get("production_order_id"))
    shipment = fulfillment.ship(order, run, quantity, carrier, sla_hours)
    return ok_object(shipment, 201)


@api.route("/fulfillment-orders/<fulfillment_order_id>/deliver", methods=["POST"])
def deliver_fulfillment_order(fulfillment_order_id):
    payload = body()
    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))
    order = get_order(fulfillment_order_id)
    run = db.store.production_orders.get(order.get("production_order_id"))
    fulfillment.deliver(order, run)
    return ok_object(order, 200)


@api.route("/fulfillment-orders/<fulfillment_order_id>/return", methods=["POST"])
def return_fulfillment_order(fulfillment_order_id):
    payload = body()
    return_quantity = require_int(payload, "return_quantity", positive=True)
    destroy_mode = require_enum(payload, "destroy_mode", ("DESTROY", "DONATE"), optional=True)
    donation_recipient_code = payload.get("donation_recipient_code")
    if destroy_mode == "DONATE" and not (isinstance(donation_recipient_code, str)
                                         and donation_recipient_code.strip()):
        fail(ERR_INVALID_REQUEST,
             "destroy_mode DONATE requires a donation_recipient_code")

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    order = get_order(fulfillment_order_id)
    run = db.store.production_orders.get(order.get("production_order_id"))
    if run is None:
        fail(ERR_PRODUCTION_ORDER_NOT_FOUND, "the referenced production order does not exist")
    if fulfillment.aggregate_ceiling_breached(run, return_quantity):
        fail(ERR_CAPACITY_EXCEEDED,
             "the return would take the run past its printable pool")
    fulfillment.return_order(order, run, return_quantity, destroy_mode)
    return ok_object(order, 200)


@api.route("/fulfillment-orders/<fulfillment_order_id>/distress", methods=["POST"])
def distress_fulfillment_order(fulfillment_order_id):
    payload = body()
    distress_reason = require_enum(payload, "distress_reason", DISTRESS_REASONS)
    destroy_mode = require_enum(payload, "destroy_mode", ("DESTROY", "DONATE"), optional=True)
    donation_recipient_code = payload.get("donation_recipient_code")
    if destroy_mode == "DONATE" and not (isinstance(donation_recipient_code, str)
                                         and donation_recipient_code.strip()):
        fail(ERR_INVALID_REQUEST,
             "destroy_mode DONATE requires a donation_recipient_code")

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    order = get_order(fulfillment_order_id)
    run = db.store.production_orders.get(order.get("production_order_id"))
    if run is not None and fulfillment.aggregate_ceiling_breached(run, 0):
        fail(ERR_CAPACITY_EXCEEDED,
             "the distress would take the run past its printable pool")
    fulfillment.distress(order, run, distress_reason, destroy_mode,
                         donation_recipient_code)
    return ok_object(order, 200)


@api.route("/fulfillment-orders/<fulfillment_order_id>/shipments", methods=["GET"])
def list_shipments(fulfillment_order_id):
    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator", "AuditOnly"))
    get_order(fulfillment_order_id)
    limit, offset = pagination()
    items = db.created_order([s for s in db.store.shipments.values()
                              if s.get("fulfillment_order_id") == fulfillment_order_id])
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)



@api.route("/royalty-accruals", methods=["GET"])
def list_royalty_accruals():
    caller = authenticate()
    require_roles(caller, ("LicensingOps", "AuditOnly"))
    limit, offset = pagination()
    items = db.created_order(list(db.store.royalty_accruals.values()))
    for arg, field in (("licensor_id", "licensor_id"),
                       ("production_order_id", "production_order_id"),
                       ("basis", "basis")):
        value = request.args.get(arg)
        if value:
            items = [r for r in items if r.get(field) == value]
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/royalty-accruals/<accrual_id>", methods=["GET"])
def read_royalty_accrual(accrual_id):
    caller = authenticate()
    require_roles(caller, ("LicensingOps", "AuditOnly"))
    accrual = db.store.royalty_accruals.get(accrual_id)
    if accrual is None:
        fail(ERR_NOT_FOUND, "royalty accrual %s does not exist" % accrual_id)
    return ok_object(accrual)



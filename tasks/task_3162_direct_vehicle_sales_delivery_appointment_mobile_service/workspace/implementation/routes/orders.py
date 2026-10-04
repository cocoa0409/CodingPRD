"""VehicleOrder routes, including the order sub-resources."""

from flask import Blueprint, request

from db import DB
from errors import fail
from repository import find, get, matches, serialize
from response import list_response, object_response
from routes.common import (
    body, bool_field, check_version, instant_field, int_field, paged,
    require_owner, string_list, text_field,
    counted,
)
from services import calculation as calc
from services import ledger, order_flow
from services import appraisal as appraisal_service

bp = Blueprint("orders", __name__)

PLACEABLE_STATES = ("DRAFT",)


def order_of(order_id):
    return get("order", order_id)


@bp.post("/orders")
def create_order():
    payload = body()
    # A body field that is absent is the malformed-request case, which is checked
    # ahead of identifier resolution; a field that is present but names nothing
    # resolves to that entity's not-found code.
    for field in ("buyer_id", "configuration_id", "jurisdiction_id",
                  "delivery_center_id"):
        if payload.get(field) is None:
            fail("ERR_INVALID_REQUEST", f"{field} is required.")
    order = order_flow.create_order(
        text_field(payload, "buyer_id"),
        text_field(payload, "configuration_id"),
        text_field(payload, "jurisdiction_id"),
        text_field(payload, "delivery_center_id"),
        int_field(payload, "order_fee_cents", None),
    )
    # PRD 2.9: the creation payload names its referenced rows, and identifiers
    # resolve left to right to the specific entity's not-found code.
    get("buyer", order["buyer_id"])
    get("configuration", order["configuration_id"])
    get("jurisdiction", order["jurisdiction_id"])
    get("center", order["delivery_center_id"])
    calc.recompute_total(order)
    return object_response(serialize(order), 201)


@bp.get("/orders")
def list_orders():
    rows = [o for o in DB.orders.values()
            if matches(request.args, "buyer_id", o["buyer_id"])
            and matches(request.args, "configuration_id", o["configuration_id"])
            and matches(request.args, "jurisdiction_id", o["jurisdiction_id"])
            and matches(request.args, "delivery_center_id", o["delivery_center_id"])
            and matches(request.args, "status", o["status"])
            and matches(request.args, "delivery_readiness_posture", o["delivery_readiness_posture"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    order = order_of(order_id)
    require_owner(order)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/configuration-changes")
def configuration_changes(order_id):
    order = order_of(order_id)
    require_owner(order)
    payload = body()
    # PRD 3.12 entry 7 sits at position 7 and the concurrency check at 19, so the
    # lock deadline is evaluated first: an in-window request never reaches a
    # deadline error at all, which is what makes the version comparison the only
    # remaining guard on an open window.
    order_flow.assert_lock_window_open(order)
    check_version(payload, "expected_order_version", order)
    add_ids = string_list(payload, "add_option_ids")
    remove_ids = string_list(payload, "remove_option_ids")
    for option_id in add_ids:
        option = get("option", option_id)
        if option["status"] != "ACTIVE":
            fail("ERR_INVALID_REQUEST", "A RETIRED option cannot be attached to an order.")
        if option["configuration_id"] != order["configuration_id"]:
            fail("ERR_INVALID_REQUEST", "The option does not belong to the ordered trim.")
    order_flow.apply_configuration_change(order, add_ids, remove_ids)
    calc.recompute_posture(order)
    order_flow.touch(order)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/place")
def place_order(order_id):
    order = order_of(order_id)
    require_owner(order)
    payload = body()
    check_version(payload, "expected_order_version", order)
    if order["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    buyer = get("buyer", order["buyer_id"])
    if buyer["status"] != "ACTIVE":
        fail("ERR_BUYER_NOT_ACTIVE")
    jurisdiction = get("jurisdiction", order["jurisdiction_id"])
    if jurisdiction["status"] != "ENACTED":
        fail("ERR_JURISDICTION_NOT_ENACTED")
    paid = sum(entry["amount_cents"] for entry in DB.ledger.values()
               if entry["order_id"] == order["id"]
               and entry["entry_type"] == "ORDER_FEE_PAYMENT")
    if paid < order["order_fee_cents"]:
        fail("ERR_ORDER_FEE_UNPAID")
    order_flow.place_order(order)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/lock-configuration")
def lock_configuration(order_id):
    order = order_of(order_id)
    payload = body()
    if order["status"] != "PLACED":
        fail("ERR_INVALID_STATE")
    check_version(payload, "expected_order_version", order)
    if order["configuration_lock_deadline"] is not None and DB.now > order["configuration_lock_deadline"]:
        fail("ERR_CONFIG_LOCK_DEADLINE_PASSED")
    order_flow.lock_configuration(order)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    order = order_of(order_id)
    require_owner(order)
    return object_response(serialize(order_flow.cancel_order(order)))


@bp.post("/orders/<order_id>/allocation")
def allocate(order_id):
    order = order_of(order_id)
    payload = body()
    # PRD 3.4: the order must be CONFIG_LOCKED and the named batch must have an
    # eligible unit; the batch's contents are the earlier of the two failures.
    if order["status"] != "CONFIG_LOCKED":
        fail("ERR_ORDER_NOT_CONFIG_LOCKED")
    batch = get("batch", text_field(payload, "batch_id"))
    order_flow.assert_eligible_unit(order, batch)
    check_version(payload, "expected_order_version", order)
    order_flow.allocate(order, batch)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/dispatch-to-transport")
def dispatch_to_transport(order_id):
    order = order_of(order_id)
    if order["status"] != "ALLOCATED":
        fail("ERR_ORDER_NOT_ALLOCATED")
    order_flow.dispatch_to_transport(order)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/arrive-at-center")
def arrive_at_center(order_id):
    order = order_of(order_id)
    if order["status"] != "IN_TRANSIT":
        fail("ERR_ORDER_NOT_IN_TRANSIT")
    order_flow.arrive_at_center(order)
    return object_response(serialize(order))


@bp.post("/orders/<order_id>/delivery-estimates")
def project_estimate(order_id):
    order = order_of(order_id)
    payload = body()
    basis = instant_field(payload, "basis_iso8601")
    window_days = int_field(payload, "window_days", 7)
    estimate = order_flow.project_estimate(order, basis, window_days)
    return object_response(serialize(estimate), 201)


@bp.get("/orders/<order_id>/delivery-estimates")
def list_order_estimates(order_id):
    order = order_of(order_id)
    require_owner(order)
    rows = [r for r in DB.estimates.values()
            if r["order_id"] == order["id"]
            and matches(request.args, "estimate_state", r["estimate_state"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/orders/<order_id>/trade-in-appraisals")
def list_order_appraisals(order_id):
    order = order_of(order_id)
    require_owner(order)
    rows = [r for r in DB.appraisals.values()
            if r["order_id"] == order["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/orders/<order_id>/financing-applications")
def list_order_applications(order_id):
    order = order_of(order_id)
    require_owner(order)
    rows = [r for r in DB.applications.values()
            if r["order_id"] == order["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/orders/<order_id>/fee-ledger-entries")
def list_order_ledger(order_id):
    order = order_of(order_id)
    require_owner(order)
    rows = ledger.entries_for(order_id=order["id"],
                              entry_type=request.args.get("entry_type"))
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.post("/orders/<order_id>/fee-ledger-entries")
def post_ledger_entry(order_id):
    order = order_of(order_id)
    payload = body()
    entry = ledger.write_entry(order["id"],
                               text_field(payload, "entry_type"),
                               int_field(payload, "amount_cents", 0),
                               text_field(payload, "reason_code"))
    return object_response(serialize(entry), 201)


@bp.get("/orders/<order_id>/allocation-units")
def list_order_units(order_id):
    order = order_of(order_id)
    rows = [r for r in DB.units.values()
            if r["order_id"] == order["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/orders/<order_id>/delivery-appointments")
def list_order_appointments(order_id):
    order = order_of(order_id)
    require_owner(order)
    rows = [r for r in DB.appointments.values()
            if r["order_id"] == order["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/orders/<order_id>/vehicles")
def list_order_vehicles(order_id):
    order = order_of(order_id)
    require_owner(order)
    rows = [r for r in DB.vehicles.values()
            if r["order_id"] == order["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.post("/orders/<order_id>/trade-in-appraisals")
def open_appraisal(order_id):
    order = order_of(order_id)
    payload = body()
    appraisal = appraisal_service.create_appraisal(
        order,
        text_field(payload, "trade_vin"),
        int_field(payload, "mileage", 0),
        int_field(payload, "gross_offer_cents", 0),
        int_field(payload, "reconditioning_estimate_cents", 0),
        instant_field(payload, "offer_valid_until"),
    )
    return object_response(serialize(appraisal), 201)


@bp.post("/orders/<order_id>/trade-in-appraisals/<appraisal_id>/appraise")
def appraise(order_id, appraisal_id):
    order = order_of(order_id)
    appraisal = get("appraisal", appraisal_id)
    if appraisal["order_id"] != order["id"]:
        fail("ERR_APPRAISAL_NOT_FOUND")
    return object_response(serialize(appraisal_service.appraise(appraisal, order)))


@bp.post("/orders/<order_id>/trade-in-appraisals/<appraisal_id>/offer")
def offer(order_id, appraisal_id):
    order = order_of(order_id)
    appraisal = get("appraisal", appraisal_id)
    if appraisal["order_id"] != order["id"]:
        fail("ERR_APPRAISAL_NOT_FOUND")
    return object_response(serialize(appraisal_service.offer(appraisal, order)))


@bp.post("/orders/<order_id>/trade-in-appraisals/<appraisal_id>/accept")
def accept(order_id, appraisal_id):
    order = order_of(order_id)
    require_owner(order)
    appraisal = get("appraisal", appraisal_id)
    if appraisal["order_id"] != order["id"]:
        fail("ERR_APPRAISAL_NOT_FOUND")
    return object_response(serialize(appraisal_service.accept(appraisal, order)))


@bp.post("/orders/<order_id>/trade-in-appraisals/<appraisal_id>/reject")
def reject(order_id, appraisal_id):
    order = order_of(order_id)
    require_owner(order)
    appraisal = get("appraisal", appraisal_id)
    if appraisal["order_id"] != order["id"]:
        fail("ERR_APPRAISAL_NOT_FOUND")
    return object_response(serialize(appraisal_service.reject(appraisal, order)))


@bp.post("/orders/<order_id>/trade-in-appraisals/<appraisal_id>/reappraise")
def reappraise(order_id, appraisal_id):
    order = order_of(order_id)
    appraisal = get("appraisal", appraisal_id)
    if appraisal["order_id"] != order["id"]:
        fail("ERR_APPRAISAL_NOT_FOUND")
    payload = body()
    updated = appraisal_service.reappraise(
        appraisal, order,
        int_field(payload, "gross_offer_cents", appraisal["gross_offer_cents"]),
        int_field(payload, "reconditioning_estimate_cents", 0),
        instant_field(payload, "offer_valid_until"),
    )
    return object_response(serialize(updated))


@bp.post("/orders/<order_id>/financing-applications")
def submit_application(order_id):
    order = order_of(order_id)
    require_owner(order)
    from services import financing as financing_service
    payload = body()
    application = financing_service.submit_application(
        order,
        int_field(payload, "term_months", 48),
        int_field(payload, "down_payment_cents", 0),
        bool_field(payload, "include_trade_in_credit", False))
    return object_response(serialize(application), 201)
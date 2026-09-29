"""Dispatch and field reporting (PRD 3.5 and 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

from calc import crew_labor_hours
from envelope import object_response
from errors import fail
from serialize import work_order_out
from services import (addon_commitments, addon_unit_total, authenticate, contract_panel_product,
                      contract_quote, crew_committed_end, crew_scheduled_orders, demobilize_contract,
                      enforce_scope, filter_fk, lookup, mobilize_contract, move_fleet,
                      panels_for_feet, product_by_code, release_reservation, windows_intersect)
from store import store
from validation import check_body, parse_pagination, plus_hours_decimal, plus_seconds, query_enum
from web import json_body, page

from routes_contracts import new_work_order

bp = Blueprint("work_orders", __name__)

READ_WORK_ORDER_ROLES = ("PlatformAdmin", "AccountManager", "DispatchCoordinator",
                         "CustomerContact", "YardAuditor")
WORK_ORDER_STATUSES = ("PLANNED", "SCHEDULED", "COMPLETED", "PARTIAL", "ABORTED",
                       "CANCELLED", "SUPERSEDED")
WORK_ORDER_TYPES = ("DELIVERY_INSTALL", "RELOCATION", "REMOVAL", "RESET")
PERMITTED_TYPES = ("DELIVERY_INSTALL", "RELOCATION", "RESET")

DISPATCH_SPEC = {
    "crew_id": {"req": True, "type": "string"},
    "scheduled_start_utc": {"req": True, "type": "instant"},
}


@bp.get("/fence-rentals/work-orders/<row_id>")
def read_work_order(row_id):
    identity = authenticate(READ_WORK_ORDER_ROLES)
    order = lookup("work_orders", row_id)
    enforce_scope(identity, lookup("contracts", order["contract_id"])["customer_account_id"])
    return object_response(work_order_out(order), 200)


@bp.get("/fence-rentals/work-orders")
def list_work_orders():
    identity = authenticate(READ_WORK_ORDER_ROLES)
    limit, offset = parse_pagination(request.args)
    status = query_enum(request.args, "status", WORK_ORDER_STATUSES)
    order_type = query_enum(request.args, "work_order_type", WORK_ORDER_TYPES)
    contract = filter_fk(request.args, "contract_id", "contracts")
    crew = filter_fk(request.args, "crew_id", "crews")
    predecessor = filter_fk(request.args, "predecessor_work_order_id", "work_orders")
    if contract is not None:
        enforce_scope(identity, contract["customer_account_id"])
    rows = []
    for order in store.sorted_rows("work_orders"):
        if contract is not None and order["contract_id"] != contract["id"]:
            continue
        if crew is not None and order["crew_id"] != crew["id"]:
            continue
        if status is not None and order["status"] != status:
            continue
        if order_type is not None and order["work_order_type"] != order_type:
            continue
        if predecessor is not None and order["predecessor_work_order_id"] != predecessor["id"]:
            continue
        if identity.is_customer:
            owner = store.contracts[order["contract_id"]]["customer_account_id"]
            if owner != identity.user_id:
                continue
        rows.append(order)
    return page(rows, work_order_out, limit, offset)


def check_permit_coverage(order, jobsite, start, end):
    """Rung 10: an APPROVED permit whose half-open window contains the whole visit."""
    if not jobsite["requires_sidewalk_closure"]:
        return
    if order["work_order_type"] not in PERMITTED_TYPES:
        return
    approved = [permit for permit in store.sorted_rows("permits")
                if permit["jobsite_id"] == jobsite["id"] and permit["status"] == "APPROVED"]
    if not approved:
        fail("ERR_PERMIT_NOT_APPROVED",
             "This jobsite has no APPROVED sidewalk-closure permit.")
    for permit in approved:
        if (permit["closure_start_utc"] <= start < permit["closure_end_utc"]
                and permit["closure_start_utc"] <= end < permit["closure_end_utc"]):
            return
    fail("ERR_PERMIT_WINDOW_ELAPSED",
         "The visit does not fall entirely inside an approved closure window.")


@bp.post("/fence-rentals/work-orders/<row_id>/dispatch")
def dispatch_work_order(row_id):
    authenticate(("DispatchCoordinator",))
    parsed = check_body(json_body(), DISPATCH_SPEC)
    order = lookup("work_orders", row_id)
    crew = lookup("crews", parsed["crew_id"])
    if order["status"] != "PLANNED":
        fail("ERR_WORK_ORDER_STATE", "Only a PLANNED visit may be dispatched.")

    contract = lookup("contracts", order["contract_id"])
    jobsite = lookup("jobsites", contract["jobsite_id"])
    start = parsed["scheduled_start_utc"]
    hours = crew_labor_hours(order["work_order_type"], order["ordered_linear_feet"],
                             addon_unit_total(contract))
    end = plus_hours_decimal(start, hours)

    check_permit_coverage(order, jobsite, start, end)                            # rung 10

    quote = contract_quote(contract)
    if quote["wind_screen"] == "SOLID_130" and not crew["certified_for_solid_screen"]:
        fail("ERR_CREW_NOT_CERTIFIED",                                           # rung 12
             "This crew is not certified for a SOLID_130 wind screen.")

    buffered_end = plus_seconds(end, 90 * 60)
    for other in crew_scheduled_orders(crew["id"], exclude_id=order["id"]):      # rung 14
        if windows_intersect(start, buffered_end, other["scheduled_start_utc"],
                             crew_committed_end(other)):
            fail("ERR_CREW_WINDOW_CONFLICT",
                 "The crew already holds a committed interval that overlaps this visit.")

    committed_hours = Decimal(0)                                                 # rung 15
    for other in crew_scheduled_orders(crew["id"], exclude_id=order["id"]):
        if other["scheduled_start_utc"].date() == start.date():
            committed_hours += Decimal(other["estimated_labor_hours"])
    if committed_hours + hours > Decimal(str(crew["daily_capacity_hours"])):
        fail("ERR_CREW_CAPACITY_EXCEEDED",
             "The crew's daily capacity for that UTC date would be exceeded.")

    panel_units = 0
    if order["work_order_type"] == "DELIVERY_INSTALL":                           # rung 19
        panel_product = contract_panel_product(contract)
        panel_units = panels_for_feet(order["ordered_linear_feet"], panel_product)
        if panel_product["available_count"] < panel_units:
            fail("ERR_INSUFFICIENT_FLEET", "The yard cannot supply that many panels.")
        for entry in addon_commitments(contract):
            addon_product = product_by_code(entry["product_code"])
            if addon_product["available_count"] < entry["unit_count"]:
                fail("ERR_INSUFFICIENT_FLEET",
                     "The yard cannot supply the committed add-on units.")

    account = lookup("accounts", contract["customer_account_id"])
    if account["credit_hold_flag"]:                                             # rung 25
        fail("ERR_ACCOUNT_CREDIT_HOLD", "The owning account is on credit hold.")

    order["crew_id"] = crew["id"]
    order["scheduled_start_utc"] = start
    order["estimated_labor_hours"] = hours
    order["scheduled_end_utc"] = end
    order["status"] = "SCHEDULED"
    if order["work_order_type"] == "DELIVERY_INSTALL":
        panel_product = contract_panel_product(contract)
        order["reserved_unit_counts"] = [{"product_code": panel_product["code"],
                                          "unit_count": panel_units}]
        move_fleet(panel_product, "available_count", "reserved_count", panel_units)
    store.touch(order)
    return object_response(work_order_out(order), 200)


def install_fleet_hop(order, contract, completed_feet, full):
    """Hop one of the mobilization cascade; a partial install strands no panel."""
    panel_product = contract_panel_product(contract)
    for entry in order["reserved_unit_counts"]:
        product = product_by_code(entry["product_code"])
        reserved = entry["unit_count"]
        if full:
            move_fleet(product, "reserved_count", "deployed_count", reserved)
            continue
        erected = panels_for_feet(completed_feet, panel_product)
        if erected > reserved:
            erected = reserved
        move_fleet(product, "reserved_count", "deployed_count", erected)
        move_fleet(product, "reserved_count", "available_count", reserved - erected)


@bp.post("/fence-rentals/work-orders/<row_id>/complete")
def complete_work_order(row_id):
    identity = authenticate(("DispatchCoordinator",))
    parsed = check_body(json_body(),
                        {"completed_linear_feet": {"req": True, "type": "int", "gt": 0}})
    order = lookup("work_orders", row_id)
    completed = parsed["completed_linear_feet"]
    if completed > order["ordered_linear_feet"]:
        fail("ERR_VALIDATION",
             "completed_linear_feet may not exceed the visit's ordered_linear_feet.")
    if order["status"] != "SCHEDULED":
        fail("ERR_WORK_ORDER_STATE", "Only a SCHEDULED visit may be reported complete.")

    contract = lookup("contracts", order["contract_id"])
    full = completed == order["ordered_linear_feet"]
    order_type = order["work_order_type"]
    if full and order_type in ("REMOVAL", "RESET", "RELOCATION"):
        if contract["lifecycle_status"] != "ACTIVE":
            fail("ERR_CONTRACT_STATE",
                 "The contract must be ACTIVE for that visit to be reported complete.")

    order["completed_linear_feet"] = completed
    order["completed_by_user_id"] = identity.user_id
    order["status"] = "COMPLETED" if full else "PARTIAL"
    store.touch(order)

    if order_type == "DELIVERY_INSTALL":
        install_fleet_hop(order, contract, completed, full)
        mobilize_contract(contract, identity.user_id)
        if not full:
            new_work_order(contract, order_type, order["ordered_linear_feet"] - completed,
                           None, predecessor_id=order["id"], relation="REMAINDER_OF")
    elif full and order_type == "REMOVAL":
        demobilize_contract(contract, order)
    elif full and order_type == "RESET":
        contract["current_phase"] = order["phase_to"]
        store.touch(contract)
    return object_response(work_order_out(order), 200)


@bp.post("/fence-rentals/work-orders/<row_id>/abort")
def abort_work_order(row_id):
    authenticate(("DispatchCoordinator",))
    parsed = check_body(json_body(), {"abort_reason_code": {"req": True, "type": "string"}})
    order = lookup("work_orders", row_id)
    if order["status"] != "SCHEDULED":
        fail("ERR_WORK_ORDER_STATE", "Only a SCHEDULED visit may be aborted.")
    release_reservation(order)
    order["crew_id"] = None
    order["abort_reason_code"] = parsed["abort_reason_code"]
    order["status"] = "ABORTED"
    store.touch(order)
    return object_response(work_order_out(order), 200)


@bp.post("/fence-rentals/work-orders/<row_id>/cancel")
def cancel_work_order(row_id):
    authenticate(("DispatchCoordinator", "AccountManager"))
    parsed = check_body(json_body(), {"cancel_reason_code": {"req": True, "type": "string"}})
    order = lookup("work_orders", row_id)
    if order["status"] not in ("PLANNED", "SCHEDULED"):
        fail("ERR_WORK_ORDER_STATE", "Only a PLANNED or SCHEDULED visit may be cancelled.")
    release_reservation(order)
    order["crew_id"] = None
    order["cancel_reason_code"] = parsed["cancel_reason_code"]
    order["status"] = "CANCELLED"
    store.touch(order)
    return object_response(work_order_out(order), 200)

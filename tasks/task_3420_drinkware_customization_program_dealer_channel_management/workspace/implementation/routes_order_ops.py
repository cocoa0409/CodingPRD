"""Order operations: slot reservation/release with waitlist promotion,
production start/complete, and the narrow personalized-goods return flow."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint

from auth import context, require_roles
from calc import (
    promote_waitlist, refresh_slot, slot_available_minutes,
)
from constants import PER_UNIT_MINUTES, RETURN_WINDOW_DAYS
from envelope import (
    get_body, opt_enum, opt_str, req_enum, req_int, req_str, success, touch,
)
from errors import fail
from routes_orders import check_buyer_owns, load_order
from serialize import ser_order
from store import DB, get_clock

bp = Blueprint("order_ops", __name__)

REASONS = ("DEFECT", "ARTWORK_MISMATCH", "BUYERS_REMORSE")
RESOLUTIONS = ("FULL_REFUND", "PARTIAL_CREDIT", "REMAKE")


@bp.post("/drinkware/customization-orders/<order_id>/reserve-slot")
def reserve_slot(order_id):
    uid, role = context()
    require_roles(role, ["Buyer"])
    order = load_order(order_id)
    check_buyer_owns(order, uid, role)
    body = get_body()
    slot_id = req_str(body, "slot_id")
    slot = DB.slots.get(slot_id)
    if slot is None:
        fail("ERR_SLOT_NOT_FOUND", "no print slot with id %s" % slot_id)
    refresh_slot(slot)
    if (order["order_state"] != "ACTIVE"
            or order["schedule_status"] != "UNSCHEDULED"
            or order["reservation_status"] not in ("NONE", "RELEASED")
            or order["payment_status"] != "AUTHORIZED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "the order is not in a reservable state")
    if slot["status"] != "OPEN":
        fail("ERR_SLOT_NOT_OPEN", "reservations require an OPEN slot")
    if slot["peak_overlap"] and order["artwork_status"] != "ART_APPROVED":
        fail("ERR_ARTWORK_NOT_APPROVED",
             "peak-window slots require approved artwork")
    if slot["technology"] != order["print_technology"]:
        fail("ERR_TECHNOLOGY_MISMATCH",
             "the slot's technology differs from the order's print_technology")
    reserved_minutes = order["quantity"] * PER_UNIT_MINUTES[order["print_technology"]]
    order["reserved_minutes"] = reserved_minutes
    order["slot_id"] = slot["id"]
    if slot_available_minutes(slot) >= reserved_minutes:
        order["reservation_status"] = "HELD"
        order["schedule_status"] = "RESERVED"
        if order["artwork_status"] == "ART_APPROVED":
            # Atomic confirm when art was already approved at reserve time.
            order["reservation_status"] = "CONFIRMED"
            order["schedule_status"] = "CONFIRMED"
    else:
        order["reservation_status"] = "WAITLISTED"
    touch(order)
    return success(ser_order(order))


@bp.post("/drinkware/customization-orders/<order_id>/release-slot")
def release_slot(order_id):
    uid, role = context()
    require_roles(role, ["Buyer"])
    order = load_order(order_id)
    check_buyer_owns(order, uid, role)
    get_body()
    if order["schedule_status"] in ("IN_PRODUCTION", "COMPLETE"):
        fail("ERR_ORDER_IN_PRODUCTION",
             "an order IN_PRODUCTION or COMPLETE cannot release its slot")
    if order["order_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is CANCELLED")
    if order["reservation_status"] not in ("HELD", "CONFIRMED", "WAITLISTED"):
        fail("ERR_INVALID_STATE_TRANSITION", "the order holds no reservation")
    slot = DB.slots.get(order["slot_id"]) if order["slot_id"] else None
    order["reservation_status"] = "RELEASED"
    order["slot_id"] = None
    order["schedule_status"] = "UNSCHEDULED"
    touch(order)
    if slot is not None:
        promote_waitlist(slot)
    return success(ser_order(order))


@bp.post("/drinkware/customization-orders/<order_id>/start-production")
def start_production(order_id):
    _, role = context()
    require_roles(role, ["ProductionLead"])
    order = load_order(order_id)
    get_body()
    if order["order_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is CANCELLED")
    if order["schedule_status"] != "CONFIRMED" or order["reservation_status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "production requires a CONFIRMED reservation")
    slot = DB.slots.get(order["slot_id"])
    if slot is None:
        fail("ERR_SLOT_NOT_FOUND", "no print slot with id %s" % order["slot_id"])
    refresh_slot(slot)
    if slot["status"] != "LOCKED":
        fail("ERR_SLOT_NOT_LOCKED", "the order's slot is not LOCKED")
    order["schedule_status"] = "IN_PRODUCTION"
    touch(order)
    return success(ser_order(order))


@bp.post("/drinkware/customization-orders/<order_id>/complete-production")
def complete_production(order_id):
    _, role = context()
    require_roles(role, ["ProductionLead"])
    order = load_order(order_id)
    body = get_body()
    qc_outcome = req_enum(body, "qc_outcome", ("PASS", "FAIL"))
    if order["order_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is CANCELLED")
    if order["schedule_status"] != "IN_PRODUCTION":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is not IN_PRODUCTION")
    if qc_outcome == "PASS":
        order["schedule_status"] = "COMPLETE"
        order["reservation_status"] = "CONSUMED"  # minutes stay booked
        if order["payment_status"] == "AUTHORIZED":
            order["payment_status"] = "CAPTURED"
        order["completed_at"] = get_clock()
    else:
        order["schedule_status"] = "CONFIRMED"  # rework loop
        order["qc_fail_count"] += 1
    touch(order)
    return success(ser_order(order))


@bp.post("/drinkware/customization-orders/<order_id>/request-return")
def request_return(order_id):
    uid, role = context()
    require_roles(role, ["Buyer"])
    order = load_order(order_id)
    check_buyer_owns(order, uid, role)
    body = get_body()
    reason = req_enum(body, "reason", REASONS)
    affected = req_int(body, "affected_unit_count",
                       minimum=1, maximum=order["quantity"])
    if (order["order_state"] != "ACTIVE"
            or order["schedule_status"] != "COMPLETE"
            or order["payment_status"] != "CAPTURED"
            or order["return_status"] != "NONE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "returns require an ACTIVE, COMPLETE, CAPTURED order with no prior return")
    if get_clock() >= order["completed_at"] + timedelta(days=RETURN_WINDOW_DAYS):
        fail("ERR_RETURN_WINDOW_CLOSED",
             "returns close 45 days after completion")
    order["return_status"] = "RETURN_REQUESTED"
    order["return_reason"] = reason
    order["affected_unit_count"] = affected
    touch(order)
    return success(ser_order(order))


@bp.post("/drinkware/customization-orders/<order_id>/decide-return")
def decide_return(order_id):
    _, role = context()
    require_roles(role, ["CustomerCare"])
    order = load_order(order_id)
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    resolution = opt_enum(body, "resolution", RESOLUTIONS)
    opt_str(body, "decision_notes")
    if decision == "APPROVE" and resolution is None:
        fail("ERR_INVALID_REQUEST", "resolution is required when approving a return")
    if order["return_status"] != "RETURN_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION", "no return is currently requested")
    if decision == "DENY":
        order["return_status"] = "RETURN_DENIED"
        touch(order)
        return success(ser_order(order))
    # Approval guards, in the PRD's declared order.
    if order["return_reason"] == "BUYERS_REMORSE":
        fail("ERR_PERSONALIZED_NOT_RETURNABLE",
             "personalized goods cannot be restocked")
    if order["return_reason"] == "ARTWORK_MISMATCH" and resolution == "PARTIAL_CREDIT":
        fail("ERR_RETURN_RESOLUTION_MISMATCH",
             "ARTWORK_MISMATCH admits only FULL_REFUND or REMAKE")
    if resolution == "PARTIAL_CREDIT" and order["affected_unit_count"] >= order["quantity"]:
        fail("ERR_RETURN_RESOLUTION_MISMATCH",
             "PARTIAL_CREDIT requires affected_unit_count < quantity; use FULL_REFUND")
    if resolution == "REMAKE":
        slot = DB.slots.get(order["slot_id"]) if order["slot_id"] else None
        if slot is None:
            fail("ERR_SLOT_NOT_FOUND", "no print slot with id %s" % order["slot_id"])
        refresh_slot(slot)
        if slot["status"] != "OPEN":
            fail("ERR_SLOT_NOT_OPEN",
                 "REMAKE re-booking requires an OPEN slot")
        if slot_available_minutes(slot) < order["reserved_minutes"]:
            fail("ERR_CAPACITY_EXCEEDED",
                 "the slot cannot cover the order's reserved_minutes")
    order["return_status"] = "RETURN_SETTLED"
    order["return_resolution"] = resolution
    if resolution == "FULL_REFUND":
        order["refund_cents"] += order["final_quote_cents"]
        order["payment_status"] = "REFUNDED"
    elif resolution == "PARTIAL_CREDIT":
        refund = int((Decimal(order["final_quote_cents"])
                      * order["affected_unit_count"]
                      / order["quantity"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        order["refund_cents"] += refund
        order["payment_status"] = "PARTIALLY_REFUNDED"
    else:  # REMAKE — capacity re-booking; goods are never restocked
        order["schedule_status"] = "CONFIRMED"
        order["reservation_status"] = "HELD"
    touch(order)
    return success(ser_order(order))

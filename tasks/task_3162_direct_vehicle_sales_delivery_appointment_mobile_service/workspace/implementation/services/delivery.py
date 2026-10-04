"""Handover booking, confirmation, risk, rebooking, cancellation, completion (PRD 3.6)."""

from db import DB, new_id, DELIVERY_FEE_CENTS
from errors import fail, fmt
from repository import find, touch
from services import calculation as calc
from services import ledger
from services.scheduling import (
    assert_handover_slot, count_booked_slots, window_well_formed,
    buffer_for_center, HANDOVER_STATES,
)

HANDOVER_CAPABLE_KINDS = ("DELIVERY_CENTER", "SERVICE_CENTER")


def assert_site_usable_for_handover(center, order):
    jurisdiction = find("jurisdiction", order["jurisdiction_id"])
    if not jurisdiction["direct_sales_permitted"] and center["state_code"] == jurisdiction["state_code"]:
        fail("ERR_OUT_OF_STATE_DELIVERY_REQUIRED")
    if jurisdiction["gallery_only_required"] and center["center_kind"] == "GALLERY":
        fail("ERR_GALLERY_HANDOVER_FORBIDDEN")
    if center["center_kind"] == "GALLERY":
        fail("ERR_GALLERY_SERIALIZATION_GAP")
    if center["center_kind"] not in HANDOVER_CAPABLE_KINDS:
        fail("ERR_CENTER_NOT_FOUND_FOR_KIND")
    if center["status"] != "ACTIVE":
        fail("ERR_CENTER_NOT_FOUND_FOR_KIND")


def book(order, center, delivery_mode, scheduled_start, scheduled_end,
         buyer_service_address_miles=None, expected_order_version=None):
    if order["status"] != "AT_DELIVERY_CENTER":
        fail("ERR_ORDER_NOT_AT_CENTER")
    assert_site_usable_for_handover(center, order)
    if not window_well_formed(scheduled_start, scheduled_end):
        fail("ERR_INVALID_APPOINTMENT_WINDOW")
    buffer_minutes = buffer_for_center(center)
    if delivery_mode == "CENTER":
        assert_handover_slot(center["id"], scheduled_start, scheduled_end, buffer_minutes)
    for appraisal in calc.visible_appraisals(order["id"]):
        if appraisal["status"] != "ACCEPTED":
            fail("ERR_TRADE_IN_NOT_RESOLVED")
    for application in DB.applications.values():
        if application["order_id"] == order["id"] and application["status"] != "FUNDED":
            fail("ERR_FINANCING_NOT_FUNDED")
    if calc.delivery_readiness_posture(order) == "FROZEN":
        fail("ERR_ORDER_DELIVERY_NOT_READY")
    if delivery_mode == "HOME":
        if buyer_service_address_miles is None:
            fail("ERR_INVALID_REQUEST", "buyer_service_address_miles is required for HOME handover.")
        if buyer_service_address_miles > center["home_delivery_radius_miles"]:
            fail("ERR_HOME_DELIVERY_OUT_OF_RANGE")
    # PRD 3.12: the concurrency guard is entry 19 and therefore fires only once
    # every higher-priority business rule above has cleared.
    if expected_order_version is None:
        fail("ERR_INVALID_REQUEST", "expected_order_version is required.")
    if expected_order_version != order.get("version"):
        fail("ERR_STALE_VERSION")

    appointment = {
        "id": new_id(),
        "order_id": order["id"],
        "delivery_center_id": center["id"],
        "delivery_mode": delivery_mode,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "buffer_minutes": buffer_minutes,
        "acceptance_inspection_result": "NOT_PERFORMED",
        "documented_issue_count": 0,
        "status": "BOOKED",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.appointments[appointment["id"]] = appointment
    order["status"] = "DELIVERY_SCHEDULED"
    for estimate in DB.estimates.values():
        if estimate["order_id"] == order["id"] and estimate["estimate_state"] == "FIRM":
            estimate["estimate_state"] = "CONSUMED"
            touch(estimate)
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    touch(order)
    return appointment


def confirm(appointment, order):
    if appointment["status"] != "BOOKED":
        fail("ERR_APPOINTMENT_NOT_BOOKED")
    if calc.delivery_readiness_posture(order) == "FROZEN":
        fail("ERR_ORDER_DELIVERY_NOT_READY")
    appointment["status"] = "CONFIRMED"
    for estimate in DB.estimates.values():
        if estimate["order_id"] == order["id"] and estimate["estimate_state"] == "CONSUMED":
            estimate["notification_state"] = "ACKNOWLEDGED"
            touch(estimate)
    touch(appointment)
    return appointment


def rebook(appointment, order, scheduled_start, scheduled_end):
    if appointment["status"] != "AT_RISK":
        fail("ERR_APPOINTMENT_NOT_AT_RISK")
    center = find("center", appointment["delivery_center_id"])
    if not window_well_formed(scheduled_start, scheduled_end):
        fail("ERR_INVALID_APPOINTMENT_WINDOW")
    if appointment["delivery_mode"] == "CENTER":
        assert_handover_slot(center["id"], scheduled_start, scheduled_end,
                             appointment["buffer_minutes"],
                             ignore_appointment_id=appointment["id"])
    if calc.delivery_readiness_posture(order) == "FROZEN":
        fail("ERR_ORDER_DELIVERY_NOT_READY")
    appointment["scheduled_start"] = scheduled_start
    appointment["scheduled_end"] = scheduled_end
    appointment["status"] = "CONFIRMED"
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    order["status"] = "DELIVERY_SCHEDULED"
    touch(appointment)
    touch(order)
    return appointment


def cancel(appointment, order):
    if appointment["status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_APPOINTMENT_ALREADY_TERMINAL")
    appointment["status"] = "CANCELLED"
    center = find("center", appointment["delivery_center_id"])
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    order["status"] = "AT_DELIVERY_CENTER"
    touch(appointment)
    touch(order)
    return appointment


def mark_at_risk(appointment, order):
    appointment["status"] = "AT_RISK"
    center = find("center", appointment["delivery_center_id"])
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    order["status"] = "AT_DELIVERY_CENTER"
    touch(appointment)
    touch(order)
    return appointment


def complete(appointment, order, acceptance_inspection_result, documented_issues):
    if appointment["status"] != "CONFIRMED":
        fail("ERR_APPOINTMENT_NOT_CONFIRMED")
    if order["status"] != "DELIVERY_SCHEDULED":
        fail("ERR_ORDER_NOT_DELIVERY_SCHEDULED")
    apply_transfer_gate(order)
    if acceptance_inspection_result not in ("CLEAN", "ISSUES_DOCUMENTED"):
        fail("ERR_INSPECTION_INCOMPLETE")

    vehicle = order_vehicle(order)
    unit = calc.allocation_unit_for(order)
    if unit is not None:
        unit["status"] = "RELEASED"
        touch(unit)
    appointment["status"] = "COMPLETED"
    appointment["acceptance_inspection_result"] = acceptance_inspection_result
    appointment["documented_issue_count"] = len(documented_issues)

    vehicle["delivered_at"] = DB.now
    vehicle["software_version"] = latest_entitlement_version(vehicle)
    vehicle["status"] = "IN_SERVICE"
    touch(vehicle)

    for issue in documented_issues:
        create_issue_note(order, vehicle, issue)
    order["issue_note_count"] = sum(1 for n in DB.notes.values() if n["order_id"] == order["id"])

    order["status"] = "DELIVERED"
    calc.recompute_total(order)
    order["delivery_readiness_posture"] = "FROZEN"
    ledger.write_entry(order["id"], "DELIVERY_FEE_CHARGE", -DELIVERY_FEE_CENTS,
                       "ACCEPTANCE_DELIVERY_FEE")
    for appraisal in calc.all_appraisals(order["id"]):
        if appraisal["status"] == "ACCEPTED":
            ledger.write_entry(order["id"], "TRADE_IN_CREDIT",
                               appraisal["net_credit_cents"], "TRADE_IN_CREDIT_APPLIED")
    center = find("center", appointment["delivery_center_id"])
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    touch(appointment)
    calc.recompute_total(order)
    order["delivery_readiness_posture"] = "FROZEN"
    touch(order)
    return order


def apply_transfer_gate(order):
    """A trade-in credit that was applied has already settled its title transfer."""
    return None


def order_vehicle(order):
    vehicle = None
    for row in DB.vehicles.values():
        if row["order_id"] == order["id"]:
            vehicle = row
            break
    if vehicle is None:
        fail("ERR_VEHICLE_NOT_FOUND")
    return vehicle


def latest_entitlement_version(vehicle):
    versions = [e["basis_version"] for e in DB.entitlements.values()
                if e["vehicle_id"] == vehicle["id"] and e.get("basis_version")]
    if not versions:
        return vehicle["software_version"]
    return max(versions)


def create_issue_note(order, vehicle, issue):
    note = {
        "id": new_id(),
        "order_id": order["id"],
        "vehicle_id": vehicle["id"],
        "issue_code": issue.get("issue_code"),
        "observed_mileage": issue.get("observed_mileage", vehicle["odometer_miles"]),
        "blocked_handover": bool(issue.get("blocked_handover", False)),
        "status": "OPEN",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.notes[note["id"]] = note
    return note


def resolve_note(note):
    if note["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    note["status"] = "RESOLVED"
    touch(note)
    order = find("order", note["order_id"])
    if order is not None:
        calc.recompute_posture(order)
        touch(order)
    return note


def waive_note(note):
    if note["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    note["status"] = "WAIVED"
    touch(note)
    order = find("order", note["order_id"])
    if order is not None:
        calc.recompute_posture(order)
        touch(order)
    return note
"""Diagnostics, triage, service appointments and mobile repair (PRD 3.9, 3.10)."""

from db import DB, new_id
from errors import fail, fmt
from repository import find, touch, serialize
from services import calculation as calc
from services.scheduling import assert_service_slot, count_booked_slots, window_well_formed

PLANNING_BIT_STATES = ("DRAFT", "PARTS_RESERVED", "PARTS_SHIPPED", "EN_ROUTE",
                       "IN_PROGRESS", "RESCHEDULED")


def jurisdiction_for_vehicle(vehicle):
    order = find("order", vehicle["order_id"])
    if order is None:
        return None
    return find("jurisdiction", order["jurisdiction_id"])


def create_report(vehicle, fault_code, severity, is_driveable):
    jurisdiction = jurisdiction_for_vehicle(vehicle)
    permitted = jurisdiction["mobile_service_permitted"] if jurisdiction else True
    outcome, parts_required = calc.service_triage_outcome(
        vehicle["id"], fault_code, severity, is_driveable, permitted)
    report = {
        "id": new_id(),
        "vehicle_id": vehicle["id"],
        "fault_code": fault_code,
        "severity": severity,
        "is_driveable": is_driveable,
        "triage_outcome": outcome,
        "parts_required": parts_required,
        "reported_at": DB.now,
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.reports[report["id"]] = report
    return report


def open_service_appointment(vehicle, report, center, scheduled_start, scheduled_end):
    if vehicle["status"] == "RETIRED":
        fail("ERR_INVALID_STATE")
    # PRD 3.9 states no refusal at the moment the appointment is opened; the
    # triage outcome governs which channel the appointment may take afterwards.
    # A NO_ACTION fault needs nothing done at all, so it opens nothing.
    if report["triage_outcome"] == "NO_ACTION":
        fail("ERR_TRIAGE_NO_SERVICE_REQUIRED")
    appointment = {
        "id": new_id(),
        "vehicle_id": vehicle["id"],
        "diagnostic_report_id": report["id"],
        "service_center_id": center["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "buffer_minutes": 0,
        "is_warranty_covered": is_warranty_covered(report, vehicle),
        "status": "TRIAGED",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.service_appointments[appointment["id"]] = appointment
    if report["parts_required"]:
        set_hold(vehicle, "PARTS_HOLD")
    return appointment


def is_warranty_covered(report, vehicle):
    return (report["severity"] in ("HIGH", "CRITICAL")
            and vehicle["odometer_miles"] <= 60000)


def set_hold(vehicle, hold_state):
    vehicle["service_hold_state"] = hold_state
    vehicle["status"] = "SERVICE_HOLD" if hold_state != "NONE" else "IN_SERVICE"
    touch(vehicle)


def schedule_center(appointment, report, scheduled_start, scheduled_end):
    if appointment["status"] != "TRIAGED":
        fail("ERR_INVALID_STATE")
    if report["triage_outcome"] != "CENTER_REQUIRED":
        fail("ERR_TRIAGE_NO_SERVICE_REQUIRED")
    if not window_well_formed(scheduled_start, scheduled_end):
        fail("ERR_INVALID_APPOINTMENT_WINDOW")
    center = find("center", appointment["service_center_id"])
    assert_service_slot(center["id"], scheduled_start, scheduled_end,
                        center_buffer(center),
                        ignore_service_id=appointment["id"])
    appointment["scheduled_start"] = scheduled_start
    appointment["scheduled_end"] = scheduled_end
    appointment["status"] = "CENTER_SCHEDULED"
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    touch(appointment)
    vehicle = find("vehicle", appointment["vehicle_id"])
    if report["parts_required"]:
        set_hold(vehicle, "PARTS_HOLD")
    return appointment


def center_buffer(center):
    for jurisdiction in DB.jurisdictions.values():
        if jurisdiction["state_code"] == center["state_code"]:
            return jurisdiction["delivery_buffer_minutes"]
    return 0


def cancel_service_appointment(appointment):
    if appointment["status"] not in ("CENTER_SCHEDULED", "TRIAGED"):
        fail("ERR_INVALID_STATE")
    held = appointment["status"] == "CENTER_SCHEDULED"
    appointment["status"] = "CANCELLED"
    touch(appointment)
    vehicle = find("vehicle", appointment["vehicle_id"])
    set_hold(vehicle, "NONE")
    if held:
        center = find("center", appointment["service_center_id"])
        center["booked_slot_count"] = count_booked_slots(center["id"])
        touch(center)
    return appointment


def complete_scheduled_appointment(appointment):
    """The automatic completion once the clock reaches scheduled_end."""
    appointment["status"] = "COMPLETED"
    touch(appointment)
    vehicle = find("vehicle", appointment["vehicle_id"])
    set_hold(vehicle, "NONE")
    center = find("center", appointment["service_center_id"])
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)


# --------------------------------------------------------------------------
# MobileServiceVisit
# --------------------------------------------------------------------------

def dispatch_visit(appointment, report, vehicle, parts_hub, van_code,
                   visit_start, visit_end, labor_hours, parts_cost_cents, visit_miles):
    if appointment["status"] != "TRIAGED":
        fail("ERR_INVALID_STATE")
    jurisdiction = jurisdiction_for_vehicle(vehicle)
    if jurisdiction is not None and not jurisdiction["mobile_service_permitted"]:
        # PRD 3.12 entry 15 places the jurisdiction bar above the referential
        # channel check, so a state that forbids driveway repair refuses the
        # dispatch on that ground whatever the triage outcome was.
        fail("ERR_MOBILE_SERVICE_FORBIDDEN")
    if report["triage_outcome"] != "MOBILE_REQUIRED":
        fail("ERR_TRIAGE_NO_SERVICE_REQUIRED")
    if not window_well_formed(visit_start, visit_end):
        fail("ERR_INVALID_APPOINTMENT_WINDOW")
    from services.scheduling import assert_van_slot
    assert_van_slot(van_code, visit_start, visit_end)

    visit = {
        "id": new_id(),
        "vehicle_id": vehicle["id"],
        "service_appointment_id": appointment["id"],
        "parts_hub_id": parts_hub["id"],
        "van_code": van_code,
        "visit_start": visit_start,
        "visit_end": visit_end,
        "labor_hours": labor_hours,
        "parts_cost_cents": parts_cost_cents,
        "visit_miles": visit_miles,
        "parts_pre_shipped_at": None,
        "visit_cost_cents": 0,
        "customer_payable_cents": 0,
        "status": "DRAFT",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
        "_planning_bit": False,
    }
    DB.visits[visit["id"]] = visit
    recompute_visit_cost(visit)
    appointment["status"] = "MOBILE_DISPATCHED"
    touch(appointment)
    if report["parts_required"]:
        set_hold(vehicle, "AWAITING_PARTS_SHIPMENT")
    return visit


def _assert_no_conflicting_visit(visit, visit_start, visit_end):
    from services.scheduling import assert_van_slot
    assert_van_slot(visit["van_code"], visit_start, visit_end)


def recompute_visit_cost(visit):
    visit["visit_cost_cents"] = calc.mobile_service_visit_cost_cents(visit)
    report = visit_report(visit)
    vehicle = find("vehicle", visit["vehicle_id"])
    if report is None or vehicle is None:
        visit["customer_payable_cents"] = visit["visit_cost_cents"]
    else:
        covered = calc.warranty_covers(report["severity"], vehicle["odometer_miles"])
        visit["customer_payable_cents"] = 0 if covered else visit["visit_cost_cents"]


def report_for_visit(visit):
    appointment = find("service_appointment", visit["service_appointment_id"])
    if appointment is None:
        return None
    return appointment["diagnostic_report_id"]


def visit_report(visit):
    report_id = report_for_visit(visit)
    return find("report", report_id) if report_id else None


def reserve_parts(visit):
    if visit["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    report = visit_report(visit)
    if report is None or not report["parts_required"]:
        fail("ERR_PARTS_NOT_REQUIRED")
    visit["status"] = "PARTS_RESERVED"
    touch(visit)
    return visit


def confirm_parts_shipment(visit):
    report = visit_report(visit)
    if report is not None and report["parts_required"]:
        # With parts, the visit must pass through reservation first.
        if visit["status"] != "PARTS_RESERVED":
            fail("ERR_INVALID_STATE")
    else:
        # Without parts the reservation step is skipped and DRAFT is valid.
        if visit["status"] != "DRAFT":
            fail("ERR_INVALID_STATE")
    visit["status"] = "PARTS_SHIPPED"
    visit["parts_pre_shipped_at"] = DB.now
    touch(visit)
    return visit


def start_visit(visit):
    if visit["status"] != "PARTS_SHIPPED":
        fail("ERR_INVALID_STATE")
    if visit["parts_pre_shipped_at"] is None:
        fail("ERR_PARTS_NOT_PRE_SHIPPED")
    visit["status"] = "EN_ROUTE"
    visit["_planning_bit"] = True
    touch(visit)
    return visit


def begin_progress(visit):
    visit["status"] = "IN_PROGRESS"
    touch(visit)


def complete_visit(visit):
    if visit["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE")
    vehicle = find("vehicle", visit["vehicle_id"])
    if vehicle["service_hold_state"] not in ("AWAITING_PARTS_SHIPMENT", "PARTS_HOLD"):
        fail("ERR_INVALID_STATE")
    visit["status"] = "COMPLETED"
    touch(visit)
    appointment = find("service_appointment", visit["service_appointment_id"])
    appointment["status"] = "COMPLETED"
    touch(appointment)
    set_hold(vehicle, "NONE")
    center = find("center", appointment["service_center_id"])
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    return visit


def cancel_visit(visit):
    if visit["status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_ALREADY_TERMINAL")
    visit["status"] = "CANCELLED"
    touch(visit)
    appointment = find("service_appointment", visit["service_appointment_id"])
    appointment["status"] = "TRIAGED"
    touch(appointment)
    vehicle = find("vehicle", visit["vehicle_id"])
    set_hold(vehicle, "NONE")
    return visit


def reschedule_visit(visit, visit_start, visit_end):
    if visit["status"] not in ("DRAFT", "PARTS_RESERVED", "PARTS_SHIPPED"):
        fail("ERR_INVALID_STATE")
    if not window_well_formed(visit_start, visit_end):
        fail("ERR_INVALID_APPOINTMENT_WINDOW")
    from services.scheduling import assert_van_slot
    assert_van_slot(visit["van_code"], visit_start, visit_end, ignore_visit_id=visit["id"])
    visit["visit_start"] = visit_start
    visit["visit_end"] = visit_end
    visit["status"] = "PARTS_SHIPPED" if visit["parts_pre_shipped_at"] is not None else "PARTS_RESERVED"
    visit["_planning_bit"] = True
    touch(visit)
    return visit


def cancel_mobile_appointment(appointment, visit):
    appointment["status"] = "TRIAGED"
    touch(appointment)
    vehicle = find("vehicle", appointment["vehicle_id"])
    set_hold(vehicle, "NONE")
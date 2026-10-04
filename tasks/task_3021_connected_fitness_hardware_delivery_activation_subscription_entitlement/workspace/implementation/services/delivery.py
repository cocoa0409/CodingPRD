"""DeliveryAppointment: windows, crew discipline and the completion cascade."""

import clock
import db
from db import LEGAL_SKUS
from errors import api_error
from services import calc
from services.common import (
    field_bool,
    field_datetime,
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)

ZONES = ("METRO", "SUBURBAN", "RURAL")
COMPLETION_GRADES = ("CLEAN", "DAMAGED")
FAILURE_REASONS = (
    "CUSTOMER_NOT_HOME",
    "ACCESS_DENIED",
    "UNSUITABLE_SPACE",
    "STAIR_CAP_EXCEEDED",
    "CREW_UNSAFE",
)

# The statuses that hold a crew window open (PRD section 2.9 / 3.1).
CREW_BUSY_STATES = ("SCHEDULED", "IN_PROGRESS")
MAX_STAIR_FLIGHTS = 5
RESCHEDULE_CEILING = 4


def create(payload):
    reject_unknown(
        payload,
        {"device_id", "hardware_order_id", "start_at", "end_at", "zone",
         "technician_crew_code", "stair_flights", "has_elevator"},
    )
    device_id = field_str(payload, "device_id")
    hardware_order_id = field_str(payload, "hardware_order_id")
    start_at = field_datetime(payload, "start_at")
    end_at = field_datetime(payload, "end_at")
    zone = field_enum(payload, "zone", ZONES)
    technician_crew_code = field_str(payload, "technician_crew_code")
    stair_flights = field_int(payload, "stair_flights", required=False, default=0, minimum=0)
    has_elevator = field_bool(payload, "has_elevator", required=False, default=False)

    # Path/body resolution is validated before any state rule: the device and
    # the order must both exist.
    db.require("devices", device_id)
    order = db.require("hardware_orders", hardware_order_id)

    if order["status"] != "PLACED":
        raise api_error(
            "ERR_INVALID_STATE",
            "A delivery appointment may only be created for an order in PLACED status.",
        )
    if start_at >= end_at:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "The proposed window must start before it ends.",
        )
    if db.crew_delivery_overlap(
        technician_crew_code, start_at, end_at, CREW_BUSY_STATES
    ):
        raise api_error(
            "ERR_TEMPORAL_OVERLAP",
            "The proposed half-open window overlaps an open appointment for this crew.",
        )

    appointment = db.create("delivery_appointments", {
        "device_id": device_id,
        "hardware_order_id": hardware_order_id,
        # zone fixes the delivery legs, which need not be posted by the caller.
        "start_at": start_at,
        "end_at": end_at,
        "zone": zone,
        "stair_flights": stair_flights,
        "has_elevator": has_elevator,
        "delivery_legs": calc.ZONE_LEGS[zone],
        "technician_crew_code": technician_crew_code,
        "status": "REQUESTED",
        "reschedule_count": 0,
        "completion_grade": None,
    })

    order["device_id"] = device_id
    order["status"] = "DELIVERY_SCHEDULED"
    db.touch(order)
    return appointment


def schedule(appointment, payload):
    reject_unknown(payload, {"start_at", "end_at"})

    if appointment["status"] != "REQUESTED":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a REQUESTED appointment may be scheduled.",
        )

    start_at = field_datetime(payload, "start_at")
    end_at = field_datetime(payload, "end_at")
    if start_at >= end_at:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "The proposed window must start before it ends.",
        )
    if db.crew_delivery_overlap(
        appointment["technician_crew_code"], start_at, end_at,
        CREW_BUSY_STATES, exclude_id=appointment["id"],
    ):
        raise api_error(
            "ERR_TEMPORAL_OVERLAP",
            "The proposed half-open window overlaps an other SCHEDULED or IN_PROGRESS appointment for this crew.",
        )

    appointment["start_at"] = start_at
    appointment["end_at"] = end_at
    appointment["status"] = "SCHEDULED"
    db.touch(appointment)
    return appointment


def start(appointment):
    if appointment["status"] != "SCHEDULED":
        raise api_error("ERR_INVALID_STATE", "Only a SCHEDULED appointment may be started.")
    if clock.now() < appointment["start_at"]:
        raise api_error(
            "ERR_WINDOW_NOT_OPEN",
            "The logical clock has not yet reached the scheduled start of this visit.",
        )
    appointment["status"] = "IN_PROGRESS"
    db.touch(appointment)
    return appointment


def complete(appointment, payload):
    reject_unknown(payload, {"completion_grade"})

    if appointment["status"] != "IN_PROGRESS":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only an IN_PROGRESS appointment may be completed.",
        )

    grade = field_enum(payload, "completion_grade", COMPLETION_GRADES)

    # The stagger-carry safety cap.
    if appointment["stair_flights"] > MAX_STAIR_FLIGHTS and not appointment["has_elevator"]:
        raise api_error(
            "ERR_STAIR_CAP_EXCEEDED",
            "The carry exceeds the five-flight stagger-carry safety cap.",
        )

    device = db.require("devices", appointment["device_id"])
    order = db.require("hardware_orders", appointment["hardware_order_id"])

    # A trade-in must be a live unit.
    if order["return_device_id"] is not None:
        trade_in = db.STORE["devices"].get(order["return_device_id"])
        if trade_in is None or trade_in["activation_status"] not in ("ACTIVE", "LOCKED"):
            raise api_error(
                "ERR_INVALID_STATE",
                "A trade-in device must be in ACTIVE or LOCKED at completion time.",
            )

    if device["membership_id"] is None:
        raise api_error(
            "ERR_INVALID_STATE",
            "A device may only be delivered against an owned membership.",
        )

    instant = clock.now()

    appointment["status"] = "COMPLETED"
    appointment["completion_grade"] = grade
    db.touch(appointment)

    # Cascade hop 1 and 2: the unit becomes DELIVERED with its own warranty
    # clock anchored on the delivery instant, not the order date.
    device["activation_status"] = "DELIVERED"
    device["provenance_source"] = "NEW_SALE"
    device["activated_at"] = instant
    device["warranty_expires_at"] = calc.delivered_warranty(instant)
    calc.recompute_device_entitlement(device)
    db.touch(device)

    # Cascade hop 3: the chronological variant re-derives the delivery fee from
    # the actual zone and writes the captured total on the same pinned basis.
    order["delivery_fee_cents"] = calc.delivery_charge(order["hardware_sku"], appointment["zone"])
    totals = calc.order_totals(order, "CHRONOLOGICAL")
    order["captured_total_cents"] = totals["total_cents"]
    order["finance_charge_cents"] = calc.order_capture_charge(order)
    order["status"] = "DELIVERED"
    db.touch(order)

    if grade == "DAMAGED":
        from services import service_order

        service_order.dispatch_damage_fault(device, order)

    membership = db.STORE["memberships"].get(device["membership_id"])
    if membership is not None:
        calc.recompute_stream_counters(membership)
        calc.recompute_posture(membership)

    return appointment


def fail(appointment, payload):
    reject_unknown(payload, {"failure_reason"})
    if appointment["status"] != "IN_PROGRESS":
        raise api_error("ERR_INVALID_STATE", "Only an IN_PROGRESS appointment may fail.")
    # Priority 3 validates the enum domain before any state rule can surface.
    field_enum(payload, "failure_reason", FAILURE_REASONS)

    # A failed visit is a field event, not an order event: the parent order
    # stays DELIVERY_SCHEDULED and reschedule_count does not move.
    appointment["status"] = "FAILED"
    db.touch(appointment)
    return appointment


def reschedule(appointment, payload):
    reject_unknown(payload, {"start_at", "end_at"})

    if appointment["status"] != "FAILED":
        raise api_error("ERR_INVALID_STATE", "Only a FAILED appointment may be rescheduled.")
    if appointment["reschedule_count"] >= RESCHEDULE_CEILING:
        raise api_error(
            "ERR_RESCHEDULE_LIMIT",
            "The appointment has already been rescheduled four times.",
        )

    start_at = field_datetime(payload, "start_at")
    end_at = field_datetime(payload, "end_at")
    if start_at >= end_at:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "The proposed window must start before it ends.",
        )
    if db.crew_delivery_overlap(
        appointment["technician_crew_code"], start_at, end_at,
        CREW_BUSY_STATES, exclude_id=appointment["id"],
    ):
        raise api_error(
            "ERR_TEMPORAL_OVERLAP",
            "The new half-open window overlaps an open appointment for this crew.",
        )

    appointment["start_at"] = start_at
    appointment["end_at"] = end_at
    appointment["reschedule_count"] = appointment["reschedule_count"] + 1
    appointment["status"] = "SCHEDULED"
    db.touch(appointment)
    return appointment


def quote(payload):
    """POST /delivery-quotes — a pure preview that writes nothing."""
    reject_unknown(
        payload,
        {"hardware_sku", "zone", "stair_flights", "has_elevator", "assembly_required"},
    )
    hardware_sku = field_enum(payload, "hardware_sku", LEGAL_SKUS)
    zone = field_enum(payload, "zone", ZONES)
    stair_flights = field_int(payload, "stair_flights", required=False, default=0, minimum=0)
    has_elevator = field_bool(payload, "has_elevator", required=False, default=False)
    field_bool(payload, "assembly_required", required=False, default=False)

    delivery_fee_cents = calc.delivery_charge(hardware_sku, zone)
    stair_carry_fee_cents = calc.stair_carry_surcharge(stair_flights, has_elevator)
    assembly_fee_cents = calc.SHIPPED_ASSEMBLY_FEE_CENTS
    return {
        "delivery_fee_cents": delivery_fee_cents,
        "stair_carry_fee_cents": stair_carry_fee_cents,
        "assembly_fee_cents": assembly_fee_cents,
        "quote_total_cents": delivery_fee_cents + stair_carry_fee_cents + assembly_fee_cents,
    }
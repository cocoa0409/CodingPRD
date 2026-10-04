"""ServiceOrder dispatch, parts logistics and the repair pipeline."""

import clock
import db
from errors import api_error
from services import calc
from services.common import (
    field_datetime,
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)

FAULT_CODES = ("NO_POWER", "BELT_SLIP", "SENSOR_FAULT", "SOFTWARE_CRASH", "FRAME_CRACK")
SAFETY_CRITICAL_CODES = ("NO_POWER", "FRAME_CRACK")

# Statuses that hold a repair crew window open.
REPAIR_BUSY_STATES = ("SCHEDULED", "REPAIR_IN_PROGRESS")

# Statuses from which a part may be reserved.
RESERVABLE_STATES = ("DISPATCHED", "DISPATCH_PENDING_PART")

# Statuses from which a repair window may be booked.  A DISPATCHED order is
# admissable because a safety-critical fault must be schedulable without a part
# (PRD section 3.6: "the safety function has to be restored first"), and such a
# fault can never park in DISPATCH_PENDING_PART.
SCHEDULABLE_STATES = ("DISPATCHED", "PART_RESERVED", "DISPATCH_PENDING_PART")


def derive_fault_class(reported_fault_code):
    return "SAFETY_CRITICAL" if reported_fault_code in SAFETY_CRITICAL_CODES else "COSMETIC"


def derive_priority(reported_fault_code, fault_class, device):
    """SAFETY_CRITICAL -> PRIORITY_SAFETY; FRAME_CRACK inside warranty ->
    PRIORITY_WARRANTY; everything else -> PRIORITY_STANDARD."""
    if fault_class == "SAFETY_CRITICAL":
        return "PRIORITY_SAFETY"
    if reported_fault_code == "FRAME_CRACK":
        warranty = device.get("warranty_expires_at")
        if warranty is not None and clock.now() <= warranty:
            return "PRIORITY_WARRANTY"
    return "PRIORITY_STANDARD"


def _new_service_order(device, order_id, reported_fault_code, diagnosis_note):
    fault_class = derive_fault_class(reported_fault_code)
    return db.create("service_orders", {
        "device_id": device["id"],
        "order_id": order_id,
        "reported_fault_code": reported_fault_code,
        "fault_class": fault_class,
        "priority": derive_priority(reported_fault_code, fault_class, device),
        "status": "DISPATCHED",
        "part_id": None,
        "reserved_part_qty": 0,
        "diagnosis_note": diagnosis_note,
        "resolved_at": None,
        "failure_before_part": False,
        "safety_functions_maintained": True,
        "technician_crew_code": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
    })


def dispatch(payload):
    reject_unknown(
        payload,
        {"device_id", "reported_fault_code", "diagnosis_note", "order_id"},
    )
    device_id = field_str(payload, "device_id")
    reported_fault_code = field_enum(payload, "reported_fault_code", FAULT_CODES)
    diagnosis_note = field_str(payload, "diagnosis_note", required=False, default=None)
    order_id = field_str(payload, "order_id", required=False, default=None)

    device = db.require("devices", device_id)
    if order_id is not None:
        order = db.require("hardware_orders", order_id)
        if order["membership_id"] != device["membership_id"]:
            raise api_error(
                "ERR_DEVICE_NOT_ON_MEMBERSHIP",
                "The originating order does not belong to the faulted device's membership.",
            )

    # Dispatch never mutates the device's entitlement lock.
    return _new_service_order(device, order_id, reported_fault_code, diagnosis_note)


def dispatch_damage_fault(device, order):
    """A DAMAGED delivery opens a FRAME_CRACK service order automatically."""
    return _new_service_order(device, order["id"], "FRAME_CRACK", None)


def reserve_part(order, payload):
    reject_unknown(payload, {"part_id", "quantity"})
    part_id = field_str(payload, "part_id")
    quantity = field_int(payload, "quantity", minimum=1)

    part = db.require("parts_inventory", part_id)
    device = db.require("devices", order["device_id"])

    if order["status"] not in RESERVABLE_STATES:
        raise api_error(
            "ERR_INVALID_STATE",
            "A part may only be reserved against a DISPATCHED or DISPATCH_PENDING_PART order.",
        )
    if part["compatible_sku"] != device["hardware_sku"]:
        raise api_error(
            "ERR_PART_SKU_MISMATCH",
            "The part's compatible_sku differs from the device's hardware_sku.",
        )

    on_hand = part["on_hand_qty"]
    if on_hand == 0:
        # No stock at all: a cosmetic fault parks for want of a part, while a
        # safety-critical fault may never be parked because the safety function
        # must be restored regardless of parts availability.
        if order["fault_class"] == "COSMETIC":
            order["status"] = "DISPATCH_PENDING_PART"
            db.touch(order)
            raise api_error(
                "ERR_PART_INSUFFICIENT",
                "No compatible part is available to serve this cosmetic fault.",
            )
        raise api_error(
            "ERR_PART_SAFETY_STOCK",
            "The reservation would drop on_hand_qty below the part's safety stock floor.",
        )

    if quantity > calc.reservable_qty(part):
        raise api_error(
            "ERR_PART_SAFETY_STOCK",
            "The reservation would drop on_hand_qty below the part's safety stock floor.",
        )

    part["reserved_qty"] = part["reserved_qty"] + quantity
    calc.recompute_stock(part)
    db.touch(part)

    order["part_id"] = part["id"]
    order["reserved_part_qty"] = quantity
    order["status"] = "PART_RESERVED"
    db.touch(order)
    return order


def release_reservation(part, payload):
    reject_unknown(payload, {"service_order_id", "quantity"})
    service_order_id = field_str(payload, "service_order_id")
    quantity = field_int(payload, "quantity", minimum=1)

    order = db.require("service_orders", service_order_id)

    if order["status"] != "PART_RESERVED":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a PART_RESERVED order may have its reservation released.",
        )
    if order["part_id"] != part["id"]:
        raise api_error(
            "ERR_RESOURCE_NOT_FOUND",
            "The service order holds no reservation against this parts inventory row.",
        )

    released = min(quantity, part["reserved_qty"])
    part["reserved_qty"] = part["reserved_qty"] - released
    calc.recompute_stock(part)
    db.touch(part)

    order["part_id"] = None
    order["reserved_part_qty"] = 0
    order["status"] = "DISPATCH_PENDING_PART"
    db.touch(order)
    return order


def schedule(order, payload):
    reject_unknown(payload, {"scheduled_start_at", "scheduled_end_at"})

    if order["status"] not in SCHEDULABLE_STATES:
        raise api_error(
            "ERR_INVALID_STATE",
            "A repair window may only be booked for a PART_RESERVED, DISPATCH_PENDING_PART "
            "or safety-critical DISPATCHED order.",
        )

    start_at = field_datetime(payload, "scheduled_start_at")
    end_at = field_datetime(payload, "scheduled_end_at")
    if start_at >= end_at:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "The proposed repair window must start before it ends.",
        )

    # Priority 7 (temporal) outranks priority 8 (referential) and 9 (aggregate).
    if db.crew_service_overlap(
        order.get("technician_crew_code"), start_at, end_at,
        REPAIR_BUSY_STATES, exclude_id=order["id"],
    ):
        raise api_error(
            "ERR_TEMPORAL_OVERLAP",
            "The proposed repair window overlaps another open service order for this crew.",
        )

    if order["part_id"] is None and order["fault_class"] != "SAFETY_CRITICAL":
        raise api_error(
            "ERR_PART_REQUIRED_FOR_SCHEDULING",
            "A cosmetic service order cannot be scheduled without a reserved part.",
        )

    device = db.require("devices", order["device_id"])
    if device["activation_status"] == "DECOMMISSIONED":
        raise api_error(
            "ERR_DISPATCH_DEVICE_NOT_OPERATIONAL",
            "The device has been decommissioned and cannot be scheduled for repair.",
        )

    order["technician_crew_code"] = order.get("technician_crew_code")
    order["scheduled_start_at"] = start_at
    order["scheduled_end_at"] = end_at
    order["status"] = "SCHEDULED"
    order["safety_functions_maintained"] = True
    db.touch(order)
    return order


def start_repair(order):
    if order["status"] != "SCHEDULED":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a SCHEDULED service order may enter repair.",
        )
    order["status"] = "REPAIR_IN_PROGRESS"
    db.touch(order)
    return order


def resolve(order, payload):
    reject_unknown(payload, {"diagnosis_note"})

    if order["status"] != "REPAIR_IN_PROGRESS":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a REPAIR_IN_PROGRESS service order may be resolved.",
        )

    note = field_str(payload, "diagnosis_note", required=False, default=None)
    if note is not None:
        order["diagnosis_note"] = note

    if order["part_id"] is None and order["fault_class"] != "SAFETY_CRITICAL":
        raise api_error(
            "ERR_PART_MISMATCH_SAFETY",
            "A cosmetic fault cannot be resolved without a reserved compatible part.",
        )

    order["status"] = "RESOLVED"
    order["resolved_at"] = clock.now()
    order["safety_functions_maintained"] = True

    if order["part_id"] is not None:
        part = db.STORE["parts_inventory"].get(order["part_id"])
        if part is not None:
            consumed = order["reserved_part_qty"]
            part["consumed_qty"] = part["consumed_qty"] + consumed
            part["reserved_qty"] = part["reserved_qty"] - consumed
            calc.recompute_stock(part)
            db.touch(part)
    db.touch(order)

    # The device's entitlement lock is left exactly as it was; only the derived
    # content flag is refreshed from the parent posture.
    device = db.STORE["devices"].get(order["device_id"])
    if device is not None:
        calc.recompute_device_entitlement(device)
        membership = db.STORE["memberships"].get(device["membership_id"])
        if membership is not None:
            calc.recompute_posture(membership)
    return order


def fail_repair(order, payload):
    reject_unknown(payload, {"diagnosis_note"})

    if order["status"] != "REPAIR_IN_PROGRESS":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a REPAIR_IN_PROGRESS service order may record a failed repair.",
        )

    note = field_str(payload, "diagnosis_note", required=False, default=None)
    if note is not None:
        order["diagnosis_note"] = note

    if order["part_id"] is None:
        order["failure_before_part"] = True

    order["status"] = "SCHEDULED"
    order["safety_functions_maintained"] = True
    db.touch(order)
    return order


def owned_by(caller, order):
    device = db.STORE["devices"].get(order["device_id"])
    membership_id = device["membership_id"] if device is not None else None
    if caller.is_owner and membership_id is not None and membership_id != caller.user_id:
        raise api_error("ERR_UNAUTHORIZED")
    return order
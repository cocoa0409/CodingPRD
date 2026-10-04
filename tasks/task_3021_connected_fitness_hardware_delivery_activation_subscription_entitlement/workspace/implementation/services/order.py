"""HardwareOrder: placement, the dual-variant total, disputes and cancellation."""

import db
from db import LEGAL_SKUS
from errors import api_error
from services import calc
from services.common import (
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)

FINANCING_METHODS = ("FULL_PAYMENT", "FINANCE_SCHEDULED")
ORDER_STATUSES = ("PLACED", "DELIVERY_SCHEDULED", "DELIVERED", "ACTIVATED", "CANCELLED")
TERMINAL_STATUSES = ("ACTIVATED", "CANCELLED")
DISPUTE_RESOLUTIONS = ("FILED", "DENIED", "APPROVED")


def create(membership, payload):
    reject_unknown(
        payload,
        {"hardware_sku", "subtotal_cents", "financing_method", "device_id"},
    )
    hardware_sku = field_enum(payload, "hardware_sku", LEGAL_SKUS)
    subtotal_cents = field_int(payload, "subtotal_cents", minimum=0)
    financing_method = field_enum(
        payload, "financing_method", FINANCING_METHODS,
        required=False, default="FULL_PAYMENT",
    )
    device_id = field_str(payload, "device_id", required=False, default=None)
    if device_id is not None:
        device = db.require("devices", device_id)
        if device["membership_id"] != membership["id"]:
            raise api_error(
                "ERR_DEVICE_NOT_ON_MEMBERSHIP",
                "The referenced device does not belong to the addressed membership.",
            )

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    if membership["posture"] in ("RESTRICTED", "FROZEN"):
        raise api_error(
            "ERR_POSTURE_RESTRICTED",
            "A membership in RESTRICTED or FROZEN posture may not place new hardware orders.",
        )

    order = db.create("hardware_orders", {
        "membership_id": membership["id"],
        "hardware_sku": hardware_sku,
        "subtotal_cents": subtotal_cents,
        "quote_total_cents": 0,
        "captured_total_cents": None,
        "delivery_fee_cents": 0,
        "stair_carry_fee_cents": calc.SHIPPED_STAIR_CARRY_FEE_CENTS,
        "assembly_fee_cents": calc.SHIPPED_ASSEMBLY_FEE_CENTS,
        "finance_charge_cents": 0,
        "financing_method": financing_method,
        "status": "PLACED",
        "refund_dispute_status": "NONE",
        "device_id": device_id,
        "return_device_id": None,
    })

    # FORWARD_LOOKING variant: no zone is known yet, so the delivery component
    # is zero and the pre-finance basis is merely the subtotal.
    totals = calc.order_totals(order, "FORWARD_LOOKING")
    order["quote_total_cents"] = totals["total_cents"]
    order["finance_charge_cents"] = totals["finance_charge_cents"]
    return order


def close_activated_orders(membership):
    """DELIVERED → ACTIVATED when the membership's activation lands.

    PRD section 3.3: activation closes the order when the order's own device has
    been linked to the same membership the order was placed under.
    """
    for order in db.STORE["hardware_orders"].values():
        if order["membership_id"] != membership["id"]:
            continue
        if order["status"] != "DELIVERED":
            continue
        if order["device_id"] is None:
            continue
        device = db.STORE["devices"].get(order["device_id"])
        if device is None:
            continue
        if device["membership_id"] != order["membership_id"]:
            continue
        if device["activation_status"] not in ("LINKED", "ACTIVE"):
            continue
        if order["financing_method"] != "FULL_PAYMENT":
            financed = any(
                plan["order_id"] == order["id"]
                and plan["status"] in ("ORIGINATED", "CURRENT", "DELINQUENT")
                for plan in db.STORE["financing_plans"].values()
            )
            if not financed:
                continue
        order["status"] = "ACTIVATED"
        db.touch(order)


def record_dispute(order, payload):
    reject_unknown(payload, {"resolution"})
    resolution = field_enum(payload, "resolution", DISPUTE_RESOLUTIONS)
    order["refund_dispute_status"] = resolution
    db.touch(order)
    return order


def redeem_refund(order, membership, payload):
    reject_unknown(payload, {"redeem_credit_cents", "expected_membership_version"})
    field_int(payload, "redeem_credit_cents", minimum=0)
    expected = field_int(payload, "expected_membership_version", required=True)
    if expected != membership["version"]:
        raise api_error(
            "ERR_MEMBERSHIP_STALE_VERSION",
            "expected_membership_version %d does not match the membership's current version %d."
            % (expected, membership["version"]),
        )

    # Priority 8 (business_referential) carries the fiscal dispute gate, and
    # priority 10 (business_fiscal) carries the purchase gate, so the fiscal
    # dispute gate is evaluated first and outranks the purchase block.
    if order["refund_dispute_status"] == "DENIED":
        raise api_error(
            "ERR_REFUND_DISPUTE_DENIED",
            "The refund dispute resolution is DENIED, so no redemptive credit may be issued.",
        )

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    if membership["posture"] in ("RESTRICTED", "FROZEN"):
        raise api_error(
            "ERR_PURCHASE_BLOCKED",
            "The membership posture blocks this redemptive credit.",
        )

    db.touch(membership)
    return order


def cancel(order):
    status = order["status"]
    if status in TERMINAL_STATUSES:
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The order has reached a terminal state and admits no further transition.",
        )
    if status not in ("PLACED", "DELIVERED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "A hardware order may only be cancelled from PLACED or DELIVERED.",
        )

    if status == "DELIVERED":
        # A financed order may not be cancelled after delivery.
        if order["financing_method"] != "FULL_PAYMENT":
            raise api_error(
                "ERR_INVALID_STATE",
                "A financed order may not be cancelled after delivery.",
            )
        # An attached ORIGINATED plan with no installments paid defaults; its
        # safety latch stays false.
        for plan in db.STORE["financing_plans"].values():
            if plan["order_id"] == order["id"] and plan["status"] == "ORIGINATED":
                plan["status"] = "DEFAULTED"
                plan["safety_disable_latched"] = False
                db.touch(plan)
                membership = db.STORE["memberships"].get(plan["membership_id"])
                if membership is not None:
                    calc.recompute_membership(membership, bump=True)

    order["status"] = "CANCELLED"
    db.touch(order)

    # Any delivery appointment still open against the order's device cancels.
    if order["device_id"] is not None:
        for appointment in db.STORE["delivery_appointments"].values():
            if appointment["device_id"] != order["device_id"]:
                continue
            if appointment["status"] in ("REQUESTED", "SCHEDULED"):
                appointment["status"] = "CANCELLED"
                db.touch(appointment)

    return order
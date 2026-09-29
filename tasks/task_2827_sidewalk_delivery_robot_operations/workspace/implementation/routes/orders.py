"""Order intake, the frozen quote, cancellation and the remedy waterfall."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, now_iso, parse_ts, public
from errors import ApiError, bad
from middleware import (
    arg_enum,
    arg_str,
    authorize,
    body,
    check_enum,
    check_int,
    check_number,
    check_str,
    check_timestamp,
    pagination,
)
from response import object_response

bp = Blueprint("orders", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "CustomerSupport", "MerchantOperator")
INTAKE_ROLES = ("MerchantOperator", "PlatformAdmin")
ORDER_STATES = (
    "RECEIVED",
    "DISPATCHED",
    "IN_TRANSIT",
    "DELIVERED",
    "EXCEPTION",
    "CANCELLED",
    "REFUNDED",
)
EXCEPTION_REASONS = ("BLOCKED_ROUTE", "ROBOT_FAULT", "WEATHER", "VANDALISM", "LATE")
REMEDY_KINDS = ("REFUND", "GOODWILL_CREDIT", "REDELIVER")
MAX_PAYLOAD_LITERS = 45.0


@bp.get("/delivery-orders")
def list_orders():
    user_id, role = authorize(READ_ROLES)
    limit, offset = pagination()
    merchant_id = arg_str("merchant_id")
    dropoff_segment_id = arg_str("dropoff_segment_id")
    order_state = arg_enum("order_state", ORDER_STATES)
    exception_reason = arg_enum("exception_reason", EXCEPTION_REASONS)
    rows = []
    for order in db.orders.values():
        if role == "MerchantOperator" and order["merchant_id"] != user_id:
            continue
        if merchant_id is not None and order["merchant_id"] != merchant_id:
            continue
        if (
            dropoff_segment_id is not None
            and order["dropoff_segment_id"] != dropoff_segment_id
        ):
            continue
        if order_state is not None and order["order_state"] != order_state:
            continue
        if exception_reason is not None and order["exception_reason"] != exception_reason:
            continue
        rows.append(order)
    return serve_list(rows, limit, offset)


@bp.get("/delivery-orders/<order_id>")
def get_order(order_id):
    user_id, role = authorize(READ_ROLES)
    order = must("orders", order_id)
    # PRD 2.1: every read a MerchantOperator makes is scoped to its own merchant,
    # and the ownership check compares X-User-ID to the merchant_id of a target order.
    if role == "MerchantOperator" and order["merchant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(public(order))


@bp.post("/delivery-orders")
def create_order():
    user_id, role = authorize(INTAKE_ROLES)
    payload = body()
    raw_merchant = payload.get("merchant_id")
    if role == "MerchantOperator" and isinstance(raw_merchant, str) and raw_merchant != "":
        if raw_merchant != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    for name in (
        "merchant_id",
        "dropoff_segment_id",
        "customer_ref",
        "payload_liters",
        "declared_value_cents",
        "promised_by_utc",
    ):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)

    merchant_id = check_str(payload, "merchant_id", 1, None)
    dropoff_segment_id = check_str(payload, "dropoff_segment_id", 1, None)
    customer_ref = check_str(payload, "customer_ref", 1, 64)
    payload_liters = check_number(payload, "payload_liters", gt=0)
    declared_value_cents = check_int(payload, "declared_value_cents", ge=0)
    if calc.dec(payload_liters) > calc.dec(MAX_PAYLOAD_LITERS):
        raise bad("Field 'payload_liters' must not exceed 45.0 litres.")
    promised_by = check_timestamp(payload, "promised_by_utc")
    if parse_ts(promised_by) <= parse_ts(now_iso()):
        raise bad("Field 'promised_by_utc' must be strictly after the current instant.")

    segment = must("segments", dropoff_segment_id)
    merchant = must("merchants", merchant_id)

    if role == "MerchantOperator" and merchant["id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if merchant["integration_state"] != "ACTIVE":
        raise ApiError("ERR_MERCHANT_NOT_ACTIVE")

    if segment["zone_id"] != merchant["zone_id"]:
        raise ApiError(
            "ERR_ZONE_MISMATCH",
            "The dropoff segment does not belong to the merchant's service zone.",
        )

    zone = db.zones.get(segment["zone_id"])
    stamp = now_iso()
    tier = calc.payload_tier(payload_liters)
    urgency = calc.urgency_flag(stamp, promised_by)
    quoted = calc.quote_at_order(zone, tier, urgency, merchant["merchant_grade"])

    order = create_row(
        db.orders,
        {
            "merchant_id": merchant["id"],
            "dropoff_segment_id": segment["id"],
            "customer_ref": customer_ref,
            "payload_liters": payload_liters,
            "declared_value_cents": declared_value_cents,
            "promised_by_utc": promised_by,
            "order_state": "RECEIVED",
            "urgency_flag": urgency,
            "payload_tier": tier,
            "quoted_fee_cents": quoted,
            "settled_fee_cents": None,
            "exception_reason": None,
            "remedy_kind": None,
            "remedy_reason_code": None,
            "remedy_amount_cents": None,
            "dispatch_attempt_count": 0,
        },
    )
    cascades.escrow_on_intake(merchant, quoted)
    return object_response(public(order), 201)


@bp.post("/delivery-orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = authorize(INTAKE_ROLES)
    payload = body()
    check_str(payload, "reason", 1, None)

    order = must("orders", order_id)
    if role == "MerchantOperator" and order["merchant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if order["order_state"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    order["order_state"] = "CANCELLED"
    bump(order)
    merchant = db.merchants.get(order["merchant_id"])
    if merchant is not None:
        cascades.escrow_to_released(merchant, order["quoted_fee_cents"])
    return object_response(public(order))


@bp.post("/delivery-orders/<order_id>/remedy")
def remedy_order(order_id):
    authorize(("CustomerSupport",))
    payload = body()
    remedy_kind = check_enum(payload, "remedy_kind", REMEDY_KINDS)

    order = must("orders", order_id)
    state = order["order_state"]

    # PRD 3.8: "Exactly one remedy may ever be issued against an order: a second
    # attempt, whatever kind it names, is refused with ERR_REMEDY_ALREADY_ISSUED
    # (HTTP 409) because remedy_kind is no longer null." A REFUND leaves the order
    # in REFUNDED, so this check has to pre-empt the source-state gate for the
    # sentence to hold for every kind the second attempt could name.
    if order["remedy_kind"] is not None:
        raise ApiError("ERR_REMEDY_ALREADY_ISSUED")
    if state not in ("EXCEPTION", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if remedy_kind == "REDELIVER" and state != "EXCEPTION":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A redelivery remedy is only available for an order in EXCEPTION.",
        )
    if order["exception_reason"] is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    merchant = db.merchants.get(order["merchant_id"])
    zone = db.zones.get(merchant["zone_id"]) if merchant is not None else None
    if zone is not None:
        cascades.refresh_zone_budget(zone)

    amount = calc.customer_remedy_amount(order, remedy_kind)

    if remedy_kind in ("REFUND", "GOODWILL_CREDIT"):
        if zone is not None and amount > zone["remedy_budget_remaining_cents"]:
            raise ApiError("ERR_REMEDY_BUDGET_EXCEEDED")

    reason_code = order["exception_reason"]
    order["remedy_kind"] = remedy_kind
    order["remedy_reason_code"] = reason_code
    order["remedy_amount_cents"] = amount

    if remedy_kind == "REFUND":
        order["order_state"] = "REFUNDED"
    elif remedy_kind == "REDELIVER":
        order["order_state"] = "RECEIVED"
        order["exception_reason"] = None
        if merchant is not None:
            cascades.released_to_escrow(merchant, order["quoted_fee_cents"])
    bump(order)

    if remedy_kind in ("REFUND", "GOODWILL_CREDIT") and zone is not None:
        zone["remedy_spent_cents"] += amount
        zone["remedy_budget_remaining_cents"] = (
            zone["remedy_budget_cents"] - zone["remedy_spent_cents"]
        )
        bump(zone)

    return object_response(public(order))

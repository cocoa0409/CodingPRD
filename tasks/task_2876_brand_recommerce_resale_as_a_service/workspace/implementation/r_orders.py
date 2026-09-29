"""Purchases, fulfilment and after-sale settlement (PRD 3.7 and 3.8)."""

from flask import Blueprint

import access
import constants as C
import serialize
import services
import store
import validators as V
from envelope import list_response, object_response, paginate
from errors import ApiError

bp = Blueprint("orders", __name__)


@bp.post("/resale-orders")
def place_resale_order():
    user_id, role = V.guard("Customer", "MerchandisingManager")
    payload = V.body()
    customer_id = V.id_field(payload, "customer_id")
    channel_id = V.id_field(payload, "channel_id")
    resale_unit_id = V.id_field(payload, "resale_unit_id")
    requested_credit_minor = V.int_field(payload, "requested_credit_minor")
    expected_version = V.int_field(payload, "expected_customer_version")

    customer = store.require("customers", customer_id)
    channel = store.require("channels", channel_id)
    unit = store.require("resale_units", resale_unit_id)

    access.require_owner(role, user_id, customer["id"])

    if unit["lifecycle_state"] != "LISTED" or unit.get("listed_channel_id") != channel["id"]:
        raise ApiError("ERR_UNIT_NOT_LISTED")
    if expected_version != customer["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_VERSION")
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED")
    if channel["status"] != "ACTIVE":
        raise ApiError("ERR_CHANNEL_NOT_ACTIVE")
    credit_policy = services.credit_policy_or_error()

    # Settlement runs in the pinned order: the fee band is keyed on the gross
    # price alone, never on the order total (PRD 3.7).
    gross_price_minor = unit["current_price_minor"]
    channel_fee_minor = services.channel_fee(gross_price_minor)
    order_total_minor = gross_price_minor + channel_fee_minor
    cap_minor = services.redemption_cap(order_total_minor, credit_policy)

    eligible = services.eligible_grants(customer["id"], channel)
    if requested_credit_minor > 0:
        live = services.live_unexpired_grants(customer["id"])
        if live and not eligible:
            raise ApiError("ERR_CREDIT_NOT_REDEEMABLE_HERE")
    if requested_credit_minor > cap_minor:
        raise ApiError("ERR_REDEMPTION_CAP_EXCEEDED")
    available_minor = sum(g["remaining_minor"] for g in eligible)
    if requested_credit_minor > available_minor:
        raise ApiError("ERR_INSUFFICIENT_CREDIT")
    credit_applied_minor = requested_credit_minor
    cash_due_minor = order_total_minor - credit_applied_minor
    if credit_applied_minor > 0 and cash_due_minor < credit_policy["min_cash_remainder_minor"]:
        raise ApiError("ERR_MIN_CASH_REMAINDER")

    order = store.create(
        "resale_orders",
        {
            "customer_id": customer["id"],
            "channel_id": channel["id"],
            "resale_unit_id": unit["id"],
            "gross_price_minor": gross_price_minor,
            "channel_fee_minor": channel_fee_minor,
            "order_total_minor": order_total_minor,
            "credit_applied_minor": credit_applied_minor,
            "cash_due_minor": cash_due_minor,
            "status": "PLACED",
            "reason_type": "NONE",
            "fulfilled_at": None,
            "warranty_expires_at": None,
            "return_requested_at": None,
            "restock_fee_minor": 0,
            "refund_cash_minor": 0,
            "refund_credit_minor": 0,
        },
    )
    if credit_applied_minor > 0:
        services.redeem_waterfall(eligible, credit_applied_minor, order["id"])
    services.recompute_customer(customer, balance=True)
    unit["lifecycle_state"] = "RESERVED"
    store.touch(unit)
    return object_response(serialize.out(order), 201)


@bp.get("/resale-orders/<order_id>")
def get_resale_order(order_id):
    user_id, role = V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    order = store.require("resale_orders", order_id)
    access.require_owner(role, user_id, order["customer_id"])
    return object_response(serialize.out(order))


@bp.get("/resale-orders")
def list_resale_orders():
    user_id, role = V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    limit, offset = V.pagination()
    status = V.enum_query("status", C.RESALE_ORDER_STATUSES)
    customer_id = V.id_query("customer_id")
    channel_id = V.id_query("channel_id")
    resale_unit_id = V.id_query("resale_unit_id")
    if customer_id is not None:
        store.require("customers", customer_id)
    if channel_id is not None:
        store.require("channels", channel_id)
    if resale_unit_id is not None:
        store.require("resale_units", resale_unit_id)
    customer_id = access.scope_customer_filter(role, user_id, customer_id)

    rows = store.rows("resale_orders")
    if customer_id is not None:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if channel_id is not None:
        rows = [o for o in rows if o["channel_id"] == channel_id]
    if resale_unit_id is not None:
        rows = [o for o in rows if o["resale_unit_id"] == resale_unit_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.get("/resale-orders/<order_id>/ledger-entries")
def list_order_entries(order_id):
    user_id, role = V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    limit, offset = V.pagination()
    entry_type = V.enum_query("entry_type", C.ENTRY_TYPES)
    order = store.require("resale_orders", order_id)
    access.require_owner(role, user_id, order["customer_id"])
    rows = services.order_entries(order["id"])
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.post("/resale-orders/<order_id>/fulfill")
def fulfill_resale_order(order_id):
    V.guard("MerchandisingManager", "ProgramAdmin")
    order = store.require("resale_orders", order_id)
    unit = store.get("resale_units", order["resale_unit_id"])
    if order["status"] != "PLACED":
        raise ApiError("ERR_ORDER_NOT_FULFILLABLE")
    if unit is None or unit["lifecycle_state"] != "RESERVED":
        raise ApiError("ERR_ORDER_NOT_FULFILLABLE")

    fulfilled_at = store.now()
    policy = store.active_grade_policy(unit["product_category"], unit["condition_grade"])
    warranty_days = 0 if policy is None else policy["warranty_days"]
    order["status"] = "FULFILLED"
    order["fulfilled_at"] = fulfilled_at
    order["warranty_expires_at"] = fulfilled_at + store.days(warranty_days)
    store.touch(order)
    unit["lifecycle_state"] = "SOLD"
    store.touch(unit)
    return object_response(serialize.out(order))


@bp.post("/resale-orders/<order_id>/return-request")
def request_return(order_id):
    user_id, role = V.guard("Customer", "ProgramAdmin")
    payload = V.body()
    reason_type = V.enum_field(payload, "reason_type", C.CLAIM_REASON_TYPES)
    order = store.require("resale_orders", order_id)
    access.require_owner(role, user_id, order["customer_id"])
    if order["status"] != "FULFILLED":
        raise ApiError("ERR_ORDER_NOT_RETURN_REQUESTABLE")

    now = store.now()
    if reason_type == "BUYER_REMORSE":
        deadline = order["fulfilled_at"] + store.days(C.REMORSE_WINDOW_DAYS)
        if now > deadline:
            raise ApiError("ERR_RETURN_WINDOW_CLOSED")
    else:
        warranty_expires_at = order.get("warranty_expires_at")
        if warranty_expires_at is None or now > warranty_expires_at:
            raise ApiError("ERR_WARRANTY_EXPIRED")

    order["status"] = "RETURN_REQUESTED"
    order["reason_type"] = reason_type
    order["return_requested_at"] = now
    store.touch(order)
    return object_response(serialize.out(order))


@bp.post("/resale-orders/<order_id>/settle-return")
def settle_return(order_id):
    V.guard("MerchandisingManager", "ProgramAdmin")
    payload = V.body()
    resolution = V.enum_field(payload, "resolution", C.RESOLUTIONS)
    order = store.require("resale_orders", order_id)
    if order["status"] != "RETURN_REQUESTED":
        raise ApiError("ERR_ORDER_RETURN_NOT_SETTLEABLE")
    if resolution == "REPLACE" and order["reason_type"] != "WARRANTY_DEFECT":
        raise ApiError("ERR_ORDER_RETURN_NOT_SETTLEABLE")

    unit = store.get("resale_units", order["resale_unit_id"])
    customer = store.get("customers", order["customer_id"])

    if resolution == "DENY":
        # The only non-terminal settlement: the claim simply evaporates.
        order["status"] = "FULFILLED"
        order["reason_type"] = "NONE"
        order["return_requested_at"] = None
        store.touch(order)
        return object_response(serialize.out(order))

    if resolution == "REFUND":
        grade_policy = services.grade_policy_or_error(
            unit["product_category"], unit["condition_grade"]
        )
        fee, refund_cash, refund_credit = services.refund_figures(order, grade_policy)

        # First link: the order and the unit.
        order["restock_fee_minor"] = fee
        order["refund_cash_minor"] = refund_cash
        order["refund_credit_minor"] = refund_credit
        order["status"] = "RETURNED"
        store.touch(order)
        unit["lifecycle_state"] = "RETURNED"
        unit["listed_channel_id"] = None
        store.touch(unit)

        # Second and third links: release along the funding grants in reverse
        # redemption order, re-expiring anything that had already lapsed.
        if refund_credit > 0:
            services.release_waterfall(order, refund_credit)

        # Fourth link: the buyer's balance, recomputed from the grants.
        services.recompute_customer(customer, balance=True)
        return object_response(serialize.out(order))

    # REPLACE: goods move, money does not, so no ledger entry is appended.
    substitute = services.select_replacement_unit(order, unit)
    order["status"] = "REPLACED"
    order["restock_fee_minor"] = 0
    order["refund_cash_minor"] = 0
    order["refund_credit_minor"] = 0
    store.touch(order)

    unit["lifecycle_state"] = "SALVAGED"
    unit["listed_channel_id"] = None
    if unit["ownership_treatment"] == "OWNED_INVENTORY":
        unit["accounting_state"] = "EXPENSED"
    store.touch(unit)

    substitute["lifecycle_state"] = "SOLD"
    substitute["replacement_for_unit_id"] = unit["id"]
    store.touch(substitute)

    services.recompute_customer(customer, diverted=True)
    return object_response(serialize.out(order))

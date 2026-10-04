# Lifetime buy routes (PRD 3.7): historical price lock, reservation, cancel.
from flask import Blueprint, request

import constants as C
import derive
from auth import require_customer_owns, require_roles
from envelope import list_response, success
from errors import (
    ApiError,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_EOL_NOTICE_NOT_ACTIVE,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_INVALID_STATE,
    ERR_LAST_ORDER_DATE_PASSED,
    ERR_LTB_QUANTITY_BELOW_MIN,
    ERR_NO_PUBLISHED_PRICING,
    ERR_NOTICE_PART_MISMATCH,
)
from lookups import get_customer, get_eol_notice, get_lifetime_buy, get_part
from serialize import lifetime_buy_public
from store import store
from validate import (
    as_int_at_least,
    as_str,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("lifetime_buys", __name__)

_CREATE_ALLOWED = {"eol_notice_id", "part_id", "customer_id", "quantity"}


@bp.post("/lifetime-buys")
def create_lifetime_buy():
    uid, role = require_roles("Customer")
    body = get_body(required=True)
    # Row 2 ownership: customer_id must equal X-User-ID.
    if "customer_id" in body and body["customer_id"] is not None:
        require_customer_owns(body["customer_id"], uid, role)
    # Row 3 existence in the global type order: part, customer, notice.
    if "part_id" in body and body["part_id"] is not None:
        part = get_part(body["part_id"])
    if "customer_id" in body and body["customer_id"] is not None:
        customer = get_customer(body["customer_id"])
    if "eol_notice_id" in body and body["eol_notice_id"] is not None:
        notice = get_eol_notice(body["eol_notice_id"])
    # Row 4 schema.
    require_fields(body, ["eol_notice_id", "part_id", "customer_id", "quantity"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    as_str(body["eol_notice_id"], "eol_notice_id")
    as_str(body["part_id"], "part_id")
    as_str(body["customer_id"], "customer_id")
    quantity = as_int_at_least(body["quantity"], "quantity", 1)

    # Row 8: clock must not be past the notice's last_order_date.
    if store.now() > notice["last_order_date"]:
        raise ApiError(ERR_LAST_ORDER_DATE_PASSED, 422, "The notice's last order date has passed")

    # Row 9 in written order: price lookup, notice ANNOUNCED, notice part match.
    schedule = derive.ltb_price_schedule(part["id"], notice["notice_date"])
    if schedule is None:
        raise ApiError(ERR_NO_PUBLISHED_PRICING, 422, "No pricing schedule was effective by the notice date")
    if notice["status"] != "ANNOUNCED":
        raise ApiError(ERR_EOL_NOTICE_NOT_ACTIVE, 422, "The referenced EOL notice is not ANNOUNCED")
    if notice["part_id"] != part["id"]:
        raise ApiError(ERR_NOTICE_PART_MISMATCH, 422, "The notice covers a different part")

    # calc_ltb_unit_price: all-units tier rule on the selected schedule.
    unit_price = derive.tier_for_quantity(schedule, quantity)["unit_price_cents"]
    ltb_value = unit_price * quantity

    # Row 10 in written order: minimum quantity, availability, credit gate.
    minimum = part["demand_rate_units_per_week"] * C.LTB_MIN_COVERAGE_WEEKS
    if quantity < minimum:
        raise ApiError(ERR_LTB_QUANTITY_BELOW_MIN, 422, "quantity must be at least demand_rate * %d" % C.LTB_MIN_COVERAGE_WEEKS)
    available = part["on_hand_units"] - derive.part_reserved_units(part["id"])
    if available < quantity:
        raise ApiError(ERR_INSUFFICIENT_INVENTORY, 422, "Insufficient available inventory for the lifetime buy")
    exposure = derive.customer_open_exposure(customer["id"])
    if exposure + ltb_value > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 422, "Lifetime buy would exceed the customer's credit limit")

    buy = {
        "eol_notice_id": notice["id"],
        "part_id": part["id"],
        "customer_id": customer["id"],
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "ltb_value_cents": ltb_value,
        "status": "APPROVED",
    }
    buy.update(store.stamp())
    store.lifetime_buys[buy["id"]] = buy
    return success(lifetime_buy_public(buy), 201)


@bp.get("/lifetime-buys")
def list_lifetime_buys():
    uid, role = require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager", "Customer")
    buys = list(store.lifetime_buys.values())
    customer_filter = request.args.get("customer_id")
    if role == "Customer":
        # A Customer principal sees only its own lifetime buys.
        customer_filter = uid
    part_filter = request.args.get("part_id")
    notice_filter = request.args.get("eol_notice_id")
    status_filter = request.args.get("status")
    if customer_filter is not None:
        buys = [b for b in buys if b["customer_id"] == customer_filter]
    if part_filter is not None:
        buys = [b for b in buys if b["part_id"] == part_filter]
    if notice_filter is not None:
        buys = [b for b in buys if b["eol_notice_id"] == notice_filter]
    if status_filter is not None:
        buys = [b for b in buys if b["status"] == status_filter]
    buys.sort(key=lambda b: b["seq"])
    return list_response(buys, lifetime_buy_public)


@bp.get("/lifetime-buys/<buy_id>")
def fetch_lifetime_buy(buy_id):
    uid, role = require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager", "Customer")
    buy = get_lifetime_buy(buy_id)
    require_customer_owns(buy["customer_id"], uid, role)
    return success(lifetime_buy_public(buy))


@bp.post("/lifetime-buys/<buy_id>/cancel")
def cancel_lifetime_buy(buy_id):
    uid, role = require_roles("Customer", "ChannelManager")
    buy = get_lifetime_buy(buy_id)
    require_customer_owns(buy["customer_id"], uid, role)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    if buy["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an APPROVED lifetime buy can be cancelled")
    buy["status"] = "CANCELLED"
    store.touch(buy)
    return success(lifetime_buy_public(buy))

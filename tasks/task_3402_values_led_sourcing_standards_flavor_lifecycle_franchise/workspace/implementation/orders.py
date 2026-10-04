"""Shop supply orders (PRD sections 2.10 and 3.8, calculation
supply_order_total).

Pricing happens once, at creation: each line is
round_half_up(pint_price_cents * quantity_pints * (1 - discount)) with a 15%
discount for NONPROFIT_PARTNER shops only; line amounts are rounded BEFORE
summation (pinned order) and total_cents is the sum of the rounded lines.
Confirmation applies, in order: shop OPERATING, every line flavor in
LIMITED_RUN/CORE_LINE, then total_cents within the shop's credit limit
(equality allowed). Allocation reserves total_pints against the plant-day
pint pool; cancelling an ALLOCATED order releases them.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from auth import authenticate, authorize
from db import STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from shops import check_shop_ownership, get_shop
from validate import PLANT_CODES, get_body, req_date, req_enum

bp = Blueprint("orders", __name__)

PARTNER_DISCOUNT_PCT = Decimal("0.15")
PLANT_DAY_ORDER_CAPACITY_PINTS = {
    "VT_WATERBURY": 12000,
    "VT_ST_ALBANS": 9000,
    "NL_HELLENDOORN": 7000,
}
ORDERABLE_FLAVOR_STATES = ("LIMITED_RUN", "CORE_LINE")


def get_order(oid):
    o = STORE["orders"].get(oid)
    if o is None:
        fail("ERR_ORDER_NOT_FOUND", "ShopSupplyOrder id does not exist")
    return o


def _parse_lines(body):
    lines = body.get("lines")
    if lines is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: lines")
    if not isinstance(lines, list) or not lines:
        fail("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    parsed = []
    for el in lines:
        if not isinstance(el, dict):
            fail("ERR_INVALID_REQUEST",
                 "each line must be an object with flavor_id and "
                 "quantity_pints")
        fid = el.get("flavor_id")
        if not isinstance(fid, str) or fid == "":
            fail("ERR_INVALID_REQUEST",
                 "each line requires a non-empty flavor_id string")
        qty = el.get("quantity_pints")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            fail("ERR_INVALID_REQUEST",
                 "each line requires quantity_pints as a positive integer")
        parsed.append({"flavor_id": fid, "quantity_pints": qty})
    return parsed


def _order_totals(shop, lines):
    discount = (PARTNER_DISCOUNT_PCT
                if shop["operator_type"] == "NONPROFIT_PARTNER"
                else Decimal("0"))
    total_cents = 0
    total_pints = 0
    for line in lines:
        flavor = STORE["flavors"].get(line["flavor_id"])
        if flavor is None:
            fail("ERR_FLAVOR_NOT_FOUND",
                 "An order line references a flavor that does not exist")
        line_cents = int((Decimal(flavor["pint_price_cents"])
                          * line["quantity_pints"]
                          * (Decimal("1") - discount)).quantize(
                              Decimal("1"), rounding=ROUND_HALF_UP))
        total_cents += line_cents
        total_pints += line["quantity_pints"]
    return total_pints, total_cents


@bp.post("/scoop-shops/<sid>/supply-orders")
def create_order(sid):
    uid, role = authenticate()
    authorize(role, ("ShopOperator",))
    check_shop_ownership(role, uid, sid)
    shop = get_shop(sid)
    body = get_body()
    production_date = req_date(body, "production_date")
    lines = _parse_lines(body)
    total_pints, total_cents = _order_totals(shop, lines)
    r = new_resource()
    r.update({
        "scoop_shop_id": sid,
        "production_date": production_date,
        "allocated_plant_code": None,
        "lines": lines,
        "total_pints": total_pints,
        "total_cents": total_cents,
        "status": "PLACED",
    })
    STORE["orders"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/scoop-shops/<sid>/supply-orders")
def list_orders(sid):
    uid, role = authenticate()
    authorize(role, ("FranchiseAdmin", "ShopOperator"))
    check_shop_ownership(role, uid, sid)
    get_shop(sid)
    status = request.args.get("status")
    items = [o for o in STORE["orders"].values() if o["scoop_shop_id"] == sid]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = [public(o) for o in sorted_items(items)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)


@bp.get("/supply-orders/<oid>")
def read_order(oid):
    uid, role = authenticate()
    authorize(role, ("FranchiseAdmin", "ShopOperator", "PlantScheduler"))
    o = get_order(oid)
    if role == "ShopOperator" and uid != o["scoop_shop_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "A ShopOperator may only read their own shop's orders")
    return ok(public(o))


@bp.post("/supply-orders/<oid>/confirm")
def confirm_order(oid):
    _, role = authenticate()
    authorize(role, ("FranchiseAdmin",))
    o = get_order(oid)
    if o["status"] != "PLACED":
        fail("ERR_INVALID_STATE", "Only a PLACED order can be confirmed")
    shop = get_shop(o["scoop_shop_id"])
    if shop["status"] != "OPERATING":
        fail("ERR_SHOP_NOT_OPERATING",
             "Order confirm requires the shop to be OPERATING")
    for line in o["lines"]:
        flavor = STORE["flavors"].get(line["flavor_id"])
        if flavor is None or flavor["status"] not in ORDERABLE_FLAVOR_STATES:
            fail("ERR_ORDER_FLAVOR_UNAVAILABLE",
                 "Every order line's flavor must be in LIMITED_RUN or "
                 "CORE_LINE")
    if o["total_cents"] > shop["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "Order total exceeds the shop's credit limit")
    o["status"] = "CONFIRMED"
    touch(o)
    return ok(public(o))


@bp.post("/supply-orders/<oid>/allocate")
def allocate_order(oid):
    _, role = authenticate()
    authorize(role, ("PlantScheduler",))
    o = get_order(oid)
    if o["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Only a CONFIRMED order can be allocated")
    body = get_body()
    plant_code = req_enum(body, "plant_code", PLANT_CODES)
    reserved = sum(
        other["total_pints"] for other in STORE["orders"].values()
        if other["allocated_plant_code"] == plant_code
        and other["production_date"] == o["production_date"]
        and other["status"] in ("ALLOCATED", "DELIVERED"))
    if reserved + o["total_pints"] > PLANT_DAY_ORDER_CAPACITY_PINTS[plant_code]:
        fail("ERR_ORDER_CAPACITY_EXCEEDED",
             "The plant-day pint pool would be exceeded")
    o["allocated_plant_code"] = plant_code
    o["status"] = "ALLOCATED"
    touch(o)
    return ok(public(o))


@bp.post("/supply-orders/<oid>/deliver")
def deliver_order(oid):
    uid, role = authenticate()
    authorize(role, ("ShopOperator",))
    o = get_order(oid)
    if uid != o["scoop_shop_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "A ShopOperator may only deliver their own shop's orders")
    if o["status"] != "ALLOCATED":
        fail("ERR_INVALID_STATE", "Only an ALLOCATED order can be delivered")
    o["status"] = "DELIVERED"
    touch(o)
    return ok(public(o))


@bp.post("/supply-orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = authenticate()
    authorize(role, ("ShopOperator",))
    o = get_order(oid)
    if uid != o["scoop_shop_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "A ShopOperator may only cancel their own shop's orders")
    if o["status"] not in ("PLACED", "CONFIRMED", "ALLOCATED"):
        fail("ERR_INVALID_STATE",
             "Only a PLACED, CONFIRMED or ALLOCATED order can be cancelled")
    # Leaving ALLOCATED releases the reserved pints from the plant-day pool.
    o["status"] = "CANCELLED"
    touch(o)
    return ok(public(o))

"""Custom cake order endpoints: intake, quoting, confirmation and the cyclic
decoration loop (PRD 3.7)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    CAKE_ORDER_STATUSES,
    COMPLEXITIES,
    as_bool,
    as_enum,
    as_int,
    as_string,
    authenticate,
    body,
    enum_filter,
    find_bake_day,
    find_cake_order,
    find_product,
    find_slot,
    scope,
)
from response import created, listing, mark_new, ok, parse_pagination, touch
from services.calc import cake_quote, decoration_lead_minutes
from services.rollups import recompute_slot, reserved_excluding
from store import by_seq, db, new_entity
from util import add_minutes

bp = Blueprint("cake_orders", __name__)


def _context(order):
    day = db.bake_days.get(order["bake_day_id"])
    slot = db.pickup_slots.get(order["pickup_slot_id"])
    product = db.products.get(order["product_id"])
    return day, slot, product


def guard_day_open(day):
    if day is not None and day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")


def guard_slot_open(slot):
    if slot is not None and slot["slot_status"] != "OPEN":
        raise ApiError("ERR_PICKUP_SLOT_CLOSED")


def apply_quote(order, product, complexity, tier_count, rush_requested, allergen_free_required, slot):
    units, subtotal, rush_fee, discount, total = cake_quote(product, complexity, tier_count, rush_requested)
    lead = decoration_lead_minutes(complexity, tier_count, allergen_free_required)
    order["decoration_units"] = units
    order["quote_subtotal_cents"] = subtotal
    order["rush_fee_cents"] = rush_fee
    order["volume_discount_cents"] = discount
    order["quote_total_cents"] = total
    order["required_decoration_lead_minutes"] = lead
    order["decoration_deadline_utc"] = add_minutes(slot["slot_start_utc"], -lead)
    return order


@bp.post("/bakery/custom-cake-orders")
def create_cake_order():
    caller = authenticate(("CakeDesk",))
    payload = body()
    day = find_bake_day(payload.get("bake_day_id"))
    scope(caller, day["department_id"])
    product = find_product(payload.get("product_id"))
    slot = find_slot(payload.get("pickup_slot_id"))
    if slot["bake_day_id"] != day["id"]:
        raise ApiError("ERR_PICKUP_SLOT_NOT_FOUND", "The window belongs to another bake day.")

    customer_name = as_string(payload, "customer_name", min_len=1, max_len=120)
    complexity = as_enum(payload, "decoration_complexity", COMPLEXITIES)
    tier_count = as_int(payload, "tier_count", minimum=1, maximum=4)
    allergen_free_required = as_bool(payload, "allergen_free_required", default=False)
    rush_requested = as_bool(payload, "rush_requested", default=False)

    guard_day_open(day)
    guard_slot_open(slot)

    if product["department_id"] != day["department_id"]:
        raise ApiError("ERR_INGREDIENT_NOT_IN_DEPARTMENT", "The product belongs to another department.")
    if not product["is_custom_cake_base"]:
        raise ApiError("ERR_NOT_CUSTOM_CAKE_BASE")

    row = new_entity(
        bake_day_id=day["id"],
        pickup_slot_id=slot["id"],
        product_id=product["id"],
        customer_name=customer_name,
        decoration_complexity=complexity,
        tier_count=tier_count,
        allergen_free_required=allergen_free_required,
        rush_requested=rush_requested,
        order_status="INTAKE",
        revision_count=0,
        decoration_units=0,
        required_decoration_lead_minutes=0,
        decoration_deadline_utc=None,
        quote_subtotal_cents=0,
        rush_fee_cents=0,
        volume_discount_cents=0,
        quote_total_cents=0,
        decoration_started_utc=None,
        ready_at_utc=None,
        picked_up_at_utc=None,
    )
    apply_quote(row, product, complexity, tier_count, rush_requested, allergen_free_required, slot)
    db.cake_orders[row["id"]] = row
    mark_new(row)
    return created(serializers.cake_order(row))


@bp.get("/bakery/custom-cake-orders/<orderId>")
def read_cake_order(orderId):
    authenticate(ANY_ROLE)
    return ok(serializers.cake_order(find_cake_order(orderId)))


@bp.get("/bakery/custom-cake-orders")
def list_cake_orders():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    bake_day_id = request.args.get("bake_day_id") or None
    pickup_slot_id = request.args.get("pickup_slot_id") or None
    product_id = request.args.get("product_id") or None
    status = enum_filter(request.args, "order_status", CAKE_ORDER_STATUSES)
    rows = []
    for row in db.cake_orders.values():
        if bake_day_id is not None and row["bake_day_id"] != bake_day_id:
            continue
        if pickup_slot_id is not None and row["pickup_slot_id"] != pickup_slot_id:
            continue
        if product_id is not None and row["product_id"] != product_id:
            continue
        if status is not None and row["order_status"] != status:
            continue
        rows.append(row)
    return listing([serializers.cake_order(row) for row in by_seq(rows)], limit, offset)


@bp.post("/bakery/custom-cake-orders/<orderId>/confirm")
def confirm_order(orderId):
    caller = authenticate(("CakeDesk",))
    order = find_cake_order(orderId)
    day, slot, product = _context(order)
    scope(caller, day["department_id"] if day else None)

    guard_day_open(day)
    if order["order_status"] != "INTAKE":
        raise ApiError("ERR_INVALID_CAKE_ORDER_STATE", "Only an INTAKE order may be confirmed.")
    guard_slot_open(slot)

    if order["allergen_free_required"] and not product["allergen_free_claim"]:
        raise ApiError("ERR_ALLERGEN_SEGREGATION_VIOLATION")

    if db.now() > order["decoration_deadline_utc"]:
        raise ApiError("ERR_DECORATION_LEAD_TIME_MISSED")

    if int(slot["reserved_decoration_units"]) + int(order["decoration_units"]) > int(
        slot["decorator_capacity_units"]
    ):
        raise ApiError("ERR_PICKUP_SLOT_CAPACITY_EXCEEDED")

    order["order_status"] = "CONFIRMED"
    touch(order)
    recompute_slot(slot)
    return ok(serializers.cake_order(order))


@bp.post("/bakery/custom-cake-orders/<orderId>/start-decoration")
def start_decoration(orderId):
    authenticate(("Decorator",))
    order = find_cake_order(orderId)
    day, slot, _product = _context(order)

    guard_day_open(day)
    if order["order_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_CAKE_ORDER_STATE", "Only a CONFIRMED order may enter decoration.")
    guard_slot_open(slot)

    order["order_status"] = "IN_DECORATION"
    order["decoration_started_utc"] = db.now()
    touch(order)
    return ok(serializers.cake_order(order))


@bp.post("/bakery/custom-cake-orders/<orderId>/request-revision")
def request_revision(orderId):
    caller = authenticate(("CakeDesk",))
    order = find_cake_order(orderId)
    day, slot, product = _context(order)
    scope(caller, day["department_id"] if day else None)
    payload = body()
    complexity = as_enum(payload, "decoration_complexity", COMPLEXITIES)
    tier_count = as_int(payload, "tier_count", required=False, minimum=1, maximum=4,
                        default=order["tier_count"])

    guard_day_open(day)
    if order["order_status"] != "IN_DECORATION":
        raise ApiError("ERR_INVALID_CAKE_ORDER_STATE", "Only an IN_DECORATION order may be revised.")
    guard_slot_open(slot)

    lead = decoration_lead_minutes(complexity, tier_count, order["allergen_free_required"])
    deadline = add_minutes(slot["slot_start_utc"], -lead)
    if db.now() > deadline:
        raise ApiError("ERR_DECORATION_LEAD_TIME_MISSED")

    if int(order["revision_count"]) >= 2:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    from services.calc import decoration_units as _decoration_units

    new_units = _decoration_units(complexity, tier_count)
    if reserved_excluding(slot, order["id"]) + new_units > int(slot["decorator_capacity_units"]):
        raise ApiError("ERR_PICKUP_SLOT_CAPACITY_EXCEEDED")

    order["revision_count"] = int(order["revision_count"]) + 1
    order["decoration_complexity"] = complexity
    order["tier_count"] = tier_count
    apply_quote(order, product, complexity, tier_count, order["rush_requested"],
                order["allergen_free_required"], slot)
    order["decoration_started_utc"] = None
    order["order_status"] = "CONFIRMED"
    touch(order)
    recompute_slot(slot)
    return ok(serializers.cake_order(order))


@bp.post("/bakery/custom-cake-orders/<orderId>/ready")
def mark_ready(orderId):
    authenticate(("Decorator",))
    order = find_cake_order(orderId)
    day, _slot, _product = _context(order)

    guard_day_open(day)
    if order["order_status"] != "IN_DECORATION":
        raise ApiError("ERR_INVALID_CAKE_ORDER_STATE", "Only an IN_DECORATION order may be marked ready.")

    order["order_status"] = "READY"
    order["ready_at_utc"] = db.now()
    touch(order)
    return ok(serializers.cake_order(order))


@bp.post("/bakery/custom-cake-orders/<orderId>/pickup")
def pickup_order(orderId):
    caller = authenticate(("CakeDesk",))
    order = find_cake_order(orderId)
    day, slot, _product = _context(order)
    scope(caller, day["department_id"] if day else None)

    guard_day_open(day)
    if order["order_status"] != "READY":
        raise ApiError("ERR_INVALID_CAKE_ORDER_STATE", "Only a READY order may be released.")

    order["order_status"] = "PICKED_UP"
    order["picked_up_at_utc"] = db.now()
    touch(order)
    if slot is not None:
        recompute_slot(slot)
    return ok(serializers.cake_order(order))

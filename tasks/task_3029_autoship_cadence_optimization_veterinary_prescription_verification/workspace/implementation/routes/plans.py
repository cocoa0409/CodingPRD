"""Autoship plan and item endpoints."""

from flask import request

import clock
import db
import serializers
from errors import fail
from middleware import body, field
from routing import Arr, Obj, endpoint, resolve
from services import calculations, compose as compose_svc, plans as plan_svc
from services.constants import CADENCE_VALUES, CANCELLATION_REASONS


def _plan_of_item(item_id):
    return db.AUTOSHIP_PLANS.get(item_id)


def _resolve_item(plan, item_id):
    item = db.AUTOSHIP_ITEMS.get(item_id)
    if item is None or item.get("autoship_plan_id") != plan["id"]:
        fail(
            "ERR_RESOURCE_NOT_FOUND",
            "No autoship item exists with id %s on this plan." % item_id,
        )
    return item


def _check_cadence_payload(cadence_days, default_quantity):
    if cadence_days is not None and int(cadence_days) not in CADENCE_VALUES:
        fail("ERR_INVALID_CADENCE", "cadence_days must be one of 14, 21, 28, 42, 56, 84.")
    if default_quantity is not None and int(default_quantity) < 1:
        fail("ERR_INVALID_CADENCE", "default_quantity must be at least 1.")


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@endpoint("/v1/autoship-plans", ["POST"], ["Customer", "CustomerService", "PharmacyTechnician"], 201)
def create_plan(caller, ):
    payload = body()
    pet_id = field(payload, "pet_id")
    pet = resolve(db.PETS, pet_id, "pet")
    blackout_start = _parse_optional_instant(payload.get("blackout_start_date"))
    blackout_end = _parse_optional_instant(payload.get("blackout_end_date"))
    row = db.mint(
        db.AUTOSHIP_PLANS,
        pet_id=pet["id"],
        plan_status="ACTIVE",
        autoship_discount_eligibility="ELIGIBLE",
        next_order_due_date=None,
        autoship_item_count=0,
        cadence_prompt_due_date=None,
        cadence_prompt_due_days_delta=0,
        blackout_start_date=blackout_start,
        blackout_end_date=blackout_end,
        released_refunds_cents=0,
        transaction_adjustments_cents=0,
    )
    return Obj(serializers.autoship_plan(row), 201)


@endpoint(
    "/v1/autoship-plans",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def list_plans(caller, ):
    rows = db.ordered(db.AUTOSHIP_PLANS.values())
    pet_id = request.args.get("pet_id")
    status = request.args.get("plan_status")
    if pet_id:
        rows = [r for r in rows if r.get("pet_id") == pet_id]
    if status:
        rows = [r for r in rows if r.get("plan_status") == status]
    if caller.is_customer:
        rows = [r for r in rows if r.get("pet_id") == caller.id]
    return Arr([serializers.autoship_plan(r) for r in rows])


@endpoint(
    "/v1/autoship-plans/<plan_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def read_plan(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    return Obj(serializers.autoship_plan(plan))


@endpoint("/v1/autoship-plans/<plan_id>/pause", ["POST"], ["Customer", "CustomerService"])
def pause_plan(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    if plan.get("plan_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE plan can be paused.")
    for order in db.ORDERS.values():
        if order.get("autoship_plan_id") == plan["id"] and order.get("order_status") == "PROCESSING":
            fail(
                "ERR_INVALID_STATE",
                "A plan with a PROCESSING order cannot be paused.",
            )
    plan["plan_status"] = "PAUSED"
    return Obj(serializers.autoship_plan(db.touch(plan)))


@endpoint("/v1/autoship-plans/<plan_id>/resume", ["POST"], ["Customer", "CustomerService"])
def resume_plan(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    if plan.get("plan_status") not in ("PAUSED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "Only a PAUSED or SUSPENDED plan can be resumed.")
    plan["plan_status"] = "ACTIVE"
    return Obj(serializers.autoship_plan(db.touch(plan)))


@endpoint(
    "/v1/autoship-plans/<plan_id>/suspend", ["POST"], ["CustomerService", "PharmacyManager"]
)
def suspend_plan(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    if plan.get("plan_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE plan can be suspended.")
    plan["plan_status"] = "SUSPENDED"
    db.touch(plan)
    # hop 1 (shipment) then hop 2 (order): the in-transit chain is parked
    plan_svc.park_in_transit_work({plan["id"]})
    return Obj(serializers.autoship_plan(plan))


@endpoint("/v1/autoship-plans/<plan_id>/cancel", ["POST"], ["Customer", "CustomerService"])
def cancel_plan(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    payload = body()
    reason = payload.get("cancellation_reason")
    if plan.get("plan_status") not in ("ACTIVE", "PAUSED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "This plan status does not admit cancellation.")
    if reason is None:
        fail("ERR_INVALID_REQUEST", "Field 'cancellation_reason' is required.")
    if reason not in CANCELLATION_REASONS:
        fail("ERR_INVALID_REQUEST", "cancellation_reason is not a declared value.")
    plan["plan_status"] = "CANCELED"
    db.touch(plan)
    plan_svc.cancel_non_terminal_orders(plan, reason)
    calculations.settle_orders_of_pet(plan.get("pet_id"))
    calculations.payment_settlement_net(plan)
    return Obj(serializers.autoship_plan(plan))


def check_composition_plan_state(plan):
    """The composition state gate, ahead of every business rule.

    PRD SS2.12: "a resource whose current status is not the transition's `from`
    status is refused with `ERR_INVALID_STATE` at HTTP 409, except that
    composition against a non-`ACTIVE` plan is refused with the more specific
    `ERR_PLAN_PAUSED` at the same status."  §3.6 turns a plan SUSPENDED by the
    verification-failure cascade into the same refusal, so both non-ACTIVE plan
    states report `ERR_PLAN_PAUSED`; composition also inherits the plan's
    `ACTIVE`-only `from` state rather than reporting an invalid transition to
    the plan itself.
    """
    status = plan.get("plan_status")
    if status in ("PAUSED", "SUSPENDED"):
        fail(
            "ERR_PLAN_PAUSED",
            "Composition is refused while the plan is not ACTIVE.",
        )
    if status != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE plan admits composition.")


@endpoint(
    "/v1/autoship-plans/<plan_id>/compose",
    ["POST"],
    ["Customer", "CustomerService", "PharmacyTechnician"],
    201,
)
def compose_plan(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    payload = body()

    # the plan's state is checked before any business rule (PRD SS2.12)
    check_composition_plan_state(plan)

    # OCC sits outside the business ladder (PRD SS2.9 / SS2.12)
    expected = payload.get("expected_plan_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "Field 'expected_plan_version' is required.")
    if int(expected) < int(plan.get("version", 1)):
        fail(
            "ERR_STALE_PLAN_VERSION",
            "expected_plan_version is older than the plan's current version.",
        )

    order = compose_svc.compose(
        plan, payload.get("promotion_code"), payload.get("override_code")
    )
    return Obj(serializers.order(order), 201)


@endpoint(
    "/v1/autoship-plans/<plan_id>/orders",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def plan_orders(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    rows = [o for o in db.ORDERS.values() if o.get("autoship_plan_id") == plan["id"]]
    return Arr([serializers.order(r) for r in db.ordered(rows)])


@endpoint(
    "/v1/autoship-plans/<plan_id>/items",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def plan_items(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    rows = [i for i in db.AUTOSHIP_ITEMS.values() if i.get("autoship_plan_id") == plan["id"]]
    product_id = request.args.get("product_id")
    if product_id:
        rows = [r for r in rows if r.get("product_id") == product_id]
    return Arr([serializers.autoship_item(r) for r in db.ordered(rows)])


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@endpoint(
    "/v1/autoship-plans/<plan_id>/items",
    ["POST"],
    ["Customer", "CustomerService", "PharmacyTechnician"],
    201,
)
def add_item(caller, plan_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    payload = body()
    product_id = field(payload, "product_id")
    product = resolve(db.PRODUCTS, product_id, "product")
    cadence_days = payload.get("cadence_days")
    default_quantity = payload.get("default_quantity")
    if cadence_days is None:
        fail("ERR_INVALID_REQUEST", "Field 'cadence_days' is required.")
    if default_quantity is None:
        fail("ERR_INVALID_REQUEST", "Field 'default_quantity' is required.")
    _check_cadence_payload(cadence_days, default_quantity)

    item = db.mint(
        db.AUTOSHIP_ITEMS,
        autoship_plan_id=plan["id"],
        product_id=product["id"],
        item_status="ACTIVE",
        verification_state="UNVERIFIED",
        cadence_days=int(cadence_days),
        autoship_item_next_due_date=clock.current(),
        unit_lifecycle_equivalent_days=None,
        cadence_prompt_state="ALIGNED",
        default_quantity=int(default_quantity),
        unit_price_cents=int(product.get("unit_price_cents", 0) or 0),
        price_protected_unit_price_cents=None,
        protection_state="PROTECTED",
    )
    plan_svc.recompute_item_projections(item)
    plan_svc.recompute_plan_aggregates(plan)
    return Obj(serializers.autoship_item(item), 201)


@endpoint(
    "/v1/autoship-plans/<plan_id>/items/<item_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def read_item(caller, plan_id, item_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    item = _resolve_item(plan, item_id)
    return Obj(serializers.autoship_item(item))


@endpoint(
    "/v1/autoship-plans/<plan_id>/items/<item_id>/cadence",
    ["POST"],
    ["Customer", "CustomerService"],
)
def change_cadence(caller, plan_id, item_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    item = _resolve_item(plan, item_id)
    payload = body()

    expected = payload.get("expected_item_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "Field 'expected_item_version' is required.")
    if int(expected) < int(item.get("version", 1)):
        fail(
            "ERR_STALE_ITEM_VERSION",
            "expected_item_version is older than the item's current version.",
        )

    cadence_days = payload.get("cadence_days")
    default_quantity = payload.get("default_quantity")
    _check_cadence_payload(cadence_days, default_quantity)

    effective_cadence = int(cadence_days) if cadence_days is not None else int(item["cadence_days"])

    # priority 17: unbuffered half-open cadence window, tested as it stands.
    now = clock.current()
    window_start = now
    window_end = clock.add_days(now, effective_cadence)
    if calculations.cadence_window_conflicts(window_start, window_end, plan):
        fail(
            "ERR_CADENCE_WINDOW_OVERLAP",
            "The requested cadence window intersects the plan's blackout interval.",
        )

    compose_svc.apply_cadence_change(item, cadence_days, default_quantity)
    return Obj(serializers.autoship_item(item))


@endpoint(
    "/v1/autoship-plans/<plan_id>/items/<item_id>/pause",
    ["POST"],
    ["Customer", "CustomerService"],
)
def pause_item(caller, plan_id, item_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    item = _resolve_item(plan, item_id)
    if item.get("item_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE item can be paused.")
    item["item_status"] = "PAUSED"
    db.touch(item)
    plan_svc.recompute_plan_aggregates(plan)
    return Obj(serializers.autoship_item(item))


@endpoint(
    "/v1/autoship-plans/<plan_id>/items/<item_id>/resume",
    ["POST"],
    ["Customer", "CustomerService"],
)
def resume_item(caller, plan_id, item_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    item = _resolve_item(plan, item_id)
    if item.get("item_status") != "PAUSED":
        fail("ERR_INVALID_STATE", "Only a PAUSED item can be resumed.")
    item["item_status"] = "ACTIVE"
    db.touch(item)
    plan_svc.recompute_plan_aggregates(plan)
    return Obj(serializers.autoship_item(item))


@endpoint(
    "/v1/autoship-plans/<plan_id>/items/<item_id>/cancel",
    ["POST"],
    ["Customer", "CustomerService"],
)
def cancel_item(caller, plan_id, item_id):
    plan = resolve(db.AUTOSHIP_PLANS, plan_id, "autoship plan")
    item = _resolve_item(plan, item_id)
    if item.get("item_status") not in ("ACTIVE", "PAUSED"):
        fail("ERR_INVALID_STATE", "Only an ACTIVE or PAUSED item can be canceled.")
    item["item_status"] = "CANCELED"
    db.touch(item)
    plan_svc.recompute_plan_aggregates(plan)
    return Obj(serializers.autoship_item(item))


@endpoint(
    "/v1/autoship-items/<item_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def read_item_by_id(caller, item_id):
    item = resolve(db.AUTOSHIP_ITEMS, item_id, "autoship item")
    return Obj(serializers.autoship_item(item))


@endpoint(
    "/v1/autoship-items/<item_id>/order-lines",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def item_order_lines(caller, item_id):
    item = resolve(db.AUTOSHIP_ITEMS, item_id, "autoship item")
    rows = [l for l in db.ORDER_LINES.values() if l.get("autoship_item_id") == item["id"]]
    return Arr([serializers.order_line(r) for r in db.ordered(rows)])


def _parse_optional_instant(value):
    if value is None or value == "":
        return None
    return clock.parse(value)
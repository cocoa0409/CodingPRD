"""Remanufacturing orders + the core credit ledger (PRD §3.9, OCC per §2.7)."""
from flask import Blueprint, request

import calculations
import cascade
import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_enum, f_dt, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("reman", __name__)

REMAN_SCOPES = ("ENGINE", "COMPONENT")
COMPONENT_TYPES = ("SCR_CATALYST", "DPF", "DOSER", "TURBO", "INJECTOR")
SPEC_LEVELS = ("STANDARD", "PLUS", "PREMIUM")
CORE_GRADES = ("A", "B", "C", "REJECT")


def _order(oid):
    return get_or_404(store.reman_orders, oid, "RemanOrder")


def _own_center(order, user_id):
    if order["service_center_id"] != user_id:
        raise ApiError("ERR_CENTER_MISMATCH", 403,
                       "ServiceAdvisor may act only for their own center")


@bp.post("/emissions/reman-orders")
def create_reman_order():
    user_id, _ = auth(("ServiceAdvisor",))
    b = body()
    unit_id = f_str(b, "engine_unit_id")
    center_id = f_str(b, "service_center_id")
    scope = f_enum(b, "reman_scope", REMAN_SCOPES)
    # component_type present iff reman_scope == COMPONENT
    if scope == "COMPONENT":
        component_type = f_enum(b, "component_type", COMPONENT_TYPES)
    else:
        if b.get("component_type") is not None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "component_type is allowed only when reman_scope is COMPONENT")
        component_type = None
    spec_level = f_enum(b, "spec_level", SPEC_LEVELS)
    price = f_int(b, "quoted_price_cents", min_v=1)
    core_value = f_int(b, "quoted_core_value_cents", min_v=0)
    return_by = f_dt(b, "expected_core_return_by")
    expected_version = f_int(b, "expected_engine_unit_version")  # non-optional (§2.7)
    # existence (priority 4), body FKs left-to-right
    unit = get_or_404(store.units, unit_id, "EngineUnit")
    center = get_or_404(store.centers, center_id, "ServiceCenter")
    # ownership (priority 5)
    if center_id != user_id:
        raise ApiError("ERR_CENTER_MISMATCH", 403,
                       "ServiceAdvisor may order only as their own center")
    # state gates (priority 7)
    if unit["lifecycle"] != "IN_SERVICE":
        raise ApiError("ERR_UNIT_NOT_IN_SERVICE", 409,
                       "The unit must be IN_SERVICE")
    if center["auth_status"] != "AUTHORIZED":
        raise ApiError("ERR_CENTER_NOT_AUTHORIZED", 409,
                       "The ordering center must be AUTHORIZED")
    # OCC (priority 8)
    if expected_version != unit["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_engine_unit_version does not match the unit's current version")
    surcharge = calculations.spec_level_surcharge(price, spec_level)
    provisional = calculations.provisional_core_credit(core_value)
    ent = new_entity()
    ent.update({
        "engine_unit_id": unit["id"],
        "service_center_id": center["id"],
        "reman_scope": scope,
        "component_type": component_type,
        "spec_level": spec_level,
        "quoted_price_cents": price,
        "quoted_core_value_cents": core_value,
        "expected_core_return_by": return_by,
        "provisional_core_credit_cents": provisional,
        "core_grade": "UNGRADED",
        "final_core_credit_cents": None,
        "spec_level_surcharge_cents": surcharge,
        "invoice_total_cents": None,
        "status": "QUOTED",
        "core_returned_at": None,
    })
    store.reman_orders[ent["id"]] = ent
    touch(unit)  # the create advances the unit's version (§3.9)
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/reman-orders")
def list_reman_orders():
    auth(ANY)
    limit, offset = page_args()
    items = list(store.reman_orders.values())
    for param, key in (("engine_unit_id", "engine_unit_id"),
                       ("service_center_id", "service_center_id"),
                       ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[key] == v]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/reman-orders/<oid>")
def get_reman_order(oid):
    auth(ANY)
    return envelope_ok(ser(_order(oid)), 200)


@bp.post("/emissions/reman-orders/<oid>/confirm")
def confirm_reman_order(oid):
    user_id, _ = auth(("ServiceAdvisor",))
    order = _order(oid)
    _own_center(order, user_id)
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "confirm requires QUOTED")
    center = store.centers.get(order["service_center_id"])
    center["core_credit_balance_cents"] += order["provisional_core_credit_cents"]
    touch(center)
    order["status"] = "AWAITING_CORE"
    touch(order)
    return envelope_ok(ser(order), 200)


@bp.post("/emissions/reman-orders/<oid>/receive-core")
def receive_core(oid):
    user_id, _ = auth(("ServiceAdvisor",))
    order = _order(oid)
    _own_center(order, user_id)
    if order["status"] != "AWAITING_CORE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "receive-core requires AWAITING_CORE")
    # temporal (priority 12): on or before the deadline is on time (inclusive)
    if clock.now_dt() > order["expected_core_return_by"]:
        raise ApiError("ERR_CORE_RETURN_WINDOW_CLOSED", 409,
                       "The core return window has closed")
    order["status"] = "CORE_RECEIVED"
    order["core_returned_at"] = clock.now_dt()
    touch(order)
    return envelope_ok(ser(order), 200)


@bp.post("/emissions/reman-orders/<oid>/grade-core")
def grade_core(oid):
    auth(("RemanPlanner",))
    b = body()
    grade = f_enum(b, "core_grade", CORE_GRADES)
    order = _order(oid)
    if order["status"] != "CORE_RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "grade-core requires CORE_RECEIVED")
    center = store.centers.get(order["service_center_id"])
    if grade == "REJECT":
        order["core_grade"] = "REJECT"
        order["final_core_credit_cents"] = 0
        order["status"] = "CORE_REJECTED"
        cascade.apply_core_reversal(center, order["provisional_core_credit_cents"])
    else:
        effective_price = order["quoted_price_cents"] + order["spec_level_surcharge_cents"]
        final = calculations.final_core_credit(
            order["quoted_core_value_cents"], grade, effective_price)
        order["core_grade"] = grade
        order["final_core_credit_cents"] = final
        order["invoice_total_cents"] = effective_price - final
        order["status"] = "CREDIT_ISSUED"
        center["core_credit_balance_cents"] += (
            final - order["provisional_core_credit_cents"])
        touch(center)
    touch(order)
    return envelope_ok(ser(order), 200)


@bp.post("/emissions/reman-orders/<oid>/forfeit-core")
def forfeit_core(oid):
    user_id, role = auth(("ServiceAdvisor", "RemanPlanner"))
    order = _order(oid)
    if role == "ServiceAdvisor":
        _own_center(order, user_id)
    if order["status"] != "AWAITING_CORE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "forfeit-core requires AWAITING_CORE")
    # temporal (priority 12): only once the deadline has strictly passed
    if not (clock.now_dt() > order["expected_core_return_by"]):
        raise ApiError("ERR_CORE_NOT_YET_LATE", 409,
                       "The core is not yet late")
    order["final_core_credit_cents"] = 0
    order["status"] = "CORE_FORFEIT"
    center = store.centers.get(order["service_center_id"])
    cascade.apply_core_reversal(center, order["provisional_core_credit_cents"])
    touch(order)
    return envelope_ok(ser(order), 200)


@bp.post("/emissions/reman-orders/<oid>/close")
def close_reman_order(oid):
    user_id, _ = auth(("ServiceAdvisor",))
    order = _order(oid)
    _own_center(order, user_id)
    if order["status"] != "CREDIT_ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "close requires CREDIT_ISSUED")
    order["status"] = "CLOSED"
    touch(order)
    return envelope_ok(ser(order), 200)

"""Production order endpoints (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize
from errors import err
from validate import paginate_params, parse_body, validate, validate_no_fields

bp = Blueprint("orders", __name__)


@bp.route("/foundry/production-orders", methods=["POST"])
def create_order():
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    vals = validate(
        parse_body(),
        [
            {"name": "product_id", "kind": "string"},
            {"name": "planned_quantity", "kind": "integer", "ge": 1},
            {"name": "scheduled_week", "kind": "integer", "ge": 1, "le": 53},
        ],
    )
    product = domain.get_or_404("products", vals["product_id"])
    if product["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_DISCONTINUED", "product is not ACTIVE")
    ent = store.make_entity()
    ent.update(
        {
            "product_id": product["id"],
            "planned_quantity": vals["planned_quantity"],
            "scheduled_week": vals["scheduled_week"],
            "state": "PLANNED",
            "poured_units": 0,
            "good_units": 0,
            "scrapped_units": 0,
            "defect_scrapped_units": 0,
            "scrap_weighted_units": Decimal("0"),
            "labor_hours_actual": None,
            "energy_kwh_actual": None,
            "unit_cost_final_cents": None,
            "margin_flag": False,
        }
    )
    store.db["orders"][ent["id"]] = ent
    return envelope.success(serialize.order(ent), status=201)


@bp.route("/foundry/production-orders", methods=["GET"])
def list_orders():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["orders"].values())
    product_id = request.args.get("product_id")
    state = request.args.get("state")
    posture = request.args.get("posture")
    if product_id is not None:
        items = [o for o in items if o["product_id"] == product_id]
    if state is not None:
        items = [o for o in items if o["state"] == state]
    if posture is not None:
        items = [o for o in items if domain.order_derived(o)[2] == posture]
    return envelope.list_payload(items, serialize.order, limit, offset)


@bp.route("/foundry/production-orders/<oid>", methods=["GET"])
def get_order(oid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = domain.get_or_404("orders", oid)
    return envelope.success(serialize.order(o))


@bp.route("/foundry/production-orders/<oid>/release", methods=["POST"])
def release_order(oid):
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    validate_no_fields()
    o = domain.get_or_404("orders", oid)
    if o["state"] != "PLANNED":
        raise err("ERR_INVALID_STATE_TRANSITION", "order is not PLANNED")
    product = store.db["products"].get(o["product_id"])
    if product is None or product["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_DISCONTINUED", "product is not ACTIVE")
    o["state"] = "MOLDING"
    store.touch(o)
    return envelope.success(serialize.order(o))


@bp.route("/foundry/production-orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    vals = validate(
        parse_body(),
        [
            {"name": "labor_hours_actual", "kind": "number"},
            {"name": "energy_kwh_actual", "kind": "number"},
        ],
    )
    o = domain.get_or_404("orders", oid)
    if o["state"] != "SEASONING":
        raise err("ERR_INVALID_STATE_TRANSITION", "order is not SEASONING")
    _idx, _tier, posture = domain.order_derived(o)
    if posture == "FROZEN":
        raise err("ERR_ORDER_FROZEN", "order posture is FROZEN")
    if o["good_units"] < calc.min_good_units(o["planned_quantity"]):
        raise err(
            "ERR_YIELD_BELOW_MINIMUM",
            "good_units below ceil(0.85 * planned_quantity)",
        )
    o["labor_hours_actual"] = vals["labor_hours_actual"]
    o["energy_kwh_actual"] = vals["energy_kwh_actual"]
    material = domain.order_material_to_date_cents(o)
    final = calc.unit_cost_final(
        material,
        vals["labor_hours_actual"],
        vals["energy_kwh_actual"],
        o["poured_units"],
        o["good_units"],
    )
    o["unit_cost_final_cents"] = final
    product = store.db["products"].get(o["product_id"])
    o["margin_flag"] = calc.margin_flag(product["wholesale_price_cents"], final)
    domain.order_closure_cascade(o)
    o["state"] = "COMPLETE"
    store.touch(o)
    return envelope.success(serialize.order(o))


@bp.route("/foundry/production-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    validate_no_fields()
    o = domain.get_or_404("orders", oid)
    if o["state"] not in ("PLANNED", "MOLDING", "POURING", "FINISHING", "SEASONING"):
        raise err("ERR_INVALID_STATE_TRANSITION", "order is already terminal")
    domain.order_closure_cascade(o)
    o["state"] = "CANCELLED"
    store.touch(o)
    return envelope.success(serialize.order(o))


@bp.route("/foundry/production-orders/<oid>/molds", methods=["GET"])
def list_order_molds(oid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    domain.get_or_404("orders", oid)
    limit, offset = paginate_params()
    items = [m for m in store.db["molds"].values() if m["production_order_id"] == oid]
    return envelope.list_payload(items, serialize.mold, limit, offset)

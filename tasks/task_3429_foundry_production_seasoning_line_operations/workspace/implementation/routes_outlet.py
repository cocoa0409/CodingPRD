"""Outlet sale endpoint (PRD 3.8)."""
from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
from authz import authenticate, authorize
from errors import err
from validate import parse_body, validate

bp = Blueprint("outlet", __name__)

OUTLET_CHANNELS = ["FACTORY_OUTLET", "MUSEUM_STORE"]


@bp.route("/foundry/outlet-sales", methods=["POST"])
def create_outlet_sale():
    uid, role = authenticate()
    authorize(role, ["OutletManager"])
    vals = validate(
        parse_body(),
        [
            {"name": "product_id", "kind": "string"},
            {"name": "channel", "kind": "enum", "values": OUTLET_CHANNELS},
            {"name": "qty", "kind": "integer", "ge": 1},
            {"name": "unit_price_cents", "kind": "integer", "ge": 0},
        ],
    )
    product = domain.get_or_404("products", vals["product_id"])
    if product["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_DISCONTINUED", "product is not ACTIVE")
    floor = calc.outlet_floor_cents(product["msrp_cents"], vals["channel"])
    if vals["unit_price_cents"] < floor:
        raise err("ERR_OUTLET_PRICE_BELOW_FLOOR", f"unit_price_cents below floor {floor}")
    rec = domain.inventory_for_product(product["id"])
    if rec is None or vals["qty"] > domain.available_units(rec):
        raise err("ERR_INSUFFICIENT_INVENTORY", "qty exceeds available_units")

    sale = store.make_leaf()
    sale.update(
        {
            "product_id": product["id"],
            "channel": vals["channel"],
            "qty": vals["qty"],
            "unit_price_cents": vals["unit_price_cents"],
            "floor_price_cents": floor,
            "recorded_by": uid,
        }
    )
    store.db["outlet_sales"][sale["id"]] = sale
    rec["on_hand_units"] -= vals["qty"]
    rec["outlet_sold_units"] += vals["qty"]
    store.touch(rec)
    return envelope.success(serialize.outlet_sale(sale), status=201)

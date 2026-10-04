"""Product catalog endpoints (PRD 3.1)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize
from errors import err
from validate import paginate_params, parse_body, validate, validate_no_fields

bp = Blueprint("products", __name__)

CATEGORIES = ["SKILLET", "DUTCH_OVEN", "GRIDDLE", "GRILL_PAN", "BAKEWARE"]


@bp.route("/foundry/products", methods=["POST"])
def create_product():
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    vals = validate(
        parse_body(),
        [
            {"name": "sku_code", "kind": "string", "nonempty": True},
            {"name": "name", "kind": "string"},
            {"name": "category", "kind": "enum", "values": CATEGORIES},
            {"name": "target_weight_oz", "kind": "number", "gt": 0},
            {"name": "weight_tolerance_oz", "kind": "number", "gt": 0},
            {"name": "target_diameter_in", "kind": "number", "gt": 0},
            {"name": "diameter_tolerance_in", "kind": "number", "gt": 0},
            {"name": "min_wall_thickness_in", "kind": "number", "gt": 0},
            {"name": "wholesale_price_cents", "kind": "integer", "ge": 0},
            {"name": "msrp_cents", "kind": "integer", "ge": 0},
            {"name": "import_landed_cost_cents", "kind": "integer", "gt": 0},
            {"name": "peak_season_start_week", "kind": "integer", "ge": 1, "le": 53},
            {"name": "peak_season_end_week", "kind": "integer", "ge": 1, "le": 53},
        ],
    )
    if vals["peak_season_start_week"] > vals["peak_season_end_week"]:
        raise err(
            "ERR_INVALID_REQUEST", "peak_season_start_week must be <= peak_season_end_week"
        )
    if vals["msrp_cents"] < vals["wholesale_price_cents"]:
        raise err("ERR_INVALID_REQUEST", "msrp_cents must be >= wholesale_price_cents")
    if any(p["sku_code"] == vals["sku_code"] for p in store.db["products"].values()):
        raise err("ERR_INVALID_REQUEST", "sku_code must be unique across all products")
    floor = calc.brand_floor_cents(vals["import_landed_cost_cents"])
    if vals["wholesale_price_cents"] < floor:
        raise err(
            "ERR_PRICE_BELOW_BRAND_FLOOR",
            f"wholesale_price_cents below brand floor {floor}",
        )

    ent = store.make_entity()
    ent.update(vals)
    ent["status"] = "ACTIVE"
    store.db["products"][ent["id"]] = ent

    inv = store.make_entity()
    inv.update(
        {
            "product_id": ent["id"],
            "on_hand_units": 0,
            "reserved_units": 0,
            "shipped_units": 0,
            "outlet_sold_units": 0,
        }
    )
    store.db["inventory"][inv["id"]] = inv
    return envelope.success(serialize.product(ent), status=201)


@bp.route("/foundry/products", methods=["GET"])
def list_products():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["products"].values())
    category = request.args.get("category")
    status = request.args.get("status")
    if category is not None:
        items = [p for p in items if p["category"] == category]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return envelope.list_payload(items, serialize.product, limit, offset)


@bp.route("/foundry/products/<pid>", methods=["GET"])
def get_product(pid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    p = domain.get_or_404("products", pid)
    return envelope.success(serialize.product(p))


@bp.route("/foundry/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    validate_no_fields()
    p = domain.get_or_404("products", pid)
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE_TRANSITION", "product is not ACTIVE")
    p["status"] = "DISCONTINUED"
    store.touch(p)
    return envelope.success(serialize.product(p))


@bp.route("/foundry/products/<pid>/outlet-sales", methods=["GET"])
def list_product_outlet_sales(pid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    domain.get_or_404("products", pid)
    limit, offset = paginate_params()
    items = [s for s in store.db["outlet_sales"].values() if s["product_id"] == pid]
    return envelope.list_payload(items, serialize.outlet_sale, limit, offset)

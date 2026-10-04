"""Product lines: create, read, list, discontinue."""
from flask import Blueprint, request

from auth import context, require_roles
from envelope import (
    get_body, new_entity, req_enum, req_int, req_str, sort_created, success,
    success_list, touch,
)
from errors import fail
from serialize import ser_product_line
from store import DB

bp = Blueprint("catalog", __name__)

CATEGORIES = ("HARD_COOLER", "SOFT_GOOD", "DRINKWARE")
ALL_ROLES_READ = [
    "PlatformAdmin", "ChannelManager", "FieldInspector", "Dealer", "Buyer",
    "PrepressTech", "ProductionLead", "WarrantyAgent", "CustomerCare",
]


def load_product_line(line_id):
    p = DB.product_lines.get(line_id)
    if p is None:
        fail("ERR_PRODUCT_LINE_NOT_FOUND", "no product line with id %s" % line_id)
    return p


@bp.post("/drinkware/product-lines")
def create_product_line():
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    body = get_body()
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORIES)
    base_sku = req_str(body, "base_sku")
    base_price = req_int(body, "base_custom_price_cents", minimum=1)
    map_price = req_int(body, "map_price_cents", minimum=1)
    min_qty = req_int(body, "min_custom_quantity", minimum=1)
    wm_lid = req_int(body, "warranty_months_lid", minimum=1)
    wm_ins = req_int(body, "warranty_months_insulation", minimum=1)
    wm_hw = req_int(body, "warranty_months_hardware", minimum=1)
    for existing in DB.product_lines.values():
        if existing["base_sku"] == base_sku:
            fail("ERR_DUPLICATE_SKU", "base_sku %s is already in use" % base_sku)
    line = new_entity({
        "name": name,
        "category": category,
        "base_sku": base_sku,
        "base_custom_price_cents": base_price,
        "map_price_cents": map_price,
        "min_custom_quantity": min_qty,
        "warranty_months_lid": wm_lid,
        "warranty_months_insulation": wm_ins,
        "warranty_months_hardware": wm_hw,
        "status": "ACTIVE",
    })
    DB.product_lines[line["id"]] = line
    return success(ser_product_line(line), 201)


@bp.get("/drinkware/product-lines/<line_id>")
def get_product_line(line_id):
    _, role = context()
    require_roles(role, ALL_ROLES_READ)
    return success(ser_product_line(load_product_line(line_id)))


@bp.get("/drinkware/product-lines")
def list_product_lines():
    _, role = context()
    require_roles(role, ALL_ROLES_READ)
    category = request.args.get("category")
    status = request.args.get("status")
    items = sort_created(list(DB.product_lines.values()))
    if category is not None:
        items = [p for p in items if p["category"] == category]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return success_list([ser_product_line(p) for p in items])


@bp.post("/drinkware/product-lines/<line_id>/discontinue")
def discontinue_product_line(line_id):
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    line = load_product_line(line_id)
    get_body()
    if line["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "product line is already DISCONTINUED")
    line["status"] = "DISCONTINUED"
    touch(line)
    return success(ser_product_line(line))

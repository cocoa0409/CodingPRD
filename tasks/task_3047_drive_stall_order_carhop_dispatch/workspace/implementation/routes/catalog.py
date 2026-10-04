"""MenuItem and CustomizationOption endpoints (PRD 3.2)."""
from db import db
from errors import not_found
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_int,
    get_enum,
    get_bool,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import menu_item as ser_item, customization_option as ser_option
from services import make_record, touch
from . import catalog_bp

CATEGORIES = ["FOOD", "DRINK", "SLUSH", "DESSERT", "ADDIN"]
SIZE_SCHEMES = ["NONE", "DRINK_SIZES"]
APPLIES_TO = ["DRINK", "SLUSH", "ANY"]
ALL_READ_ROLES = ["PlatformAdmin", "ShiftManager", "Carhop", "KitchenStaff", "Customer"]


@catalog_bp.route("/menu-items", methods=["POST"])
def create_menu_item():
    require_auth(["PlatformAdmin"])
    body = body_json()
    sku = get_str(body, "sku", required=True)
    name = get_str(body, "name", required=True)
    category = get_enum(body, "category", CATEGORIES, required=True)
    base_price = get_int(body, "base_price_cents", required=True, minimum=0)
    size_scheme = get_enum(body, "size_scheme", SIZE_SCHEMES, default="NONE")
    hp = get_bool(body, "half_price_eligible", default=False)
    rec = make_record()
    rec.update(
        {
            "sku": sku,
            "name": name,
            "category": category,
            "base_price_cents": base_price,
            "size_scheme": size_scheme,
            "half_price_eligible": hp,
            "status": "ACTIVE",
        }
    )
    db.menu_items[rec["id"]] = rec
    return success_object(ser_item(rec), 201)


@catalog_bp.route("/menu-items", methods=["GET"])
def list_menu_items():
    require_auth(ALL_READ_ROLES)
    from flask import request

    category = request.args.get("category")
    status = request.args.get("status")
    if category is not None and category not in CATEGORIES:
        from errors import invalid_request

        invalid_request("category must be a valid menu category")
    if status is not None and status not in ("ACTIVE", "RETIRED"):
        from errors import invalid_request

        invalid_request("status must be ACTIVE or RETIRED")
    items = list(db.menu_items.values())
    if category is not None:
        items = [i for i in items if i["category"] == category]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return success_array([ser_item(i) for i in page], limit, offset, total)


@catalog_bp.route("/menu-items/<itemId>", methods=["GET"])
def get_menu_item(itemId):
    require_auth(ALL_READ_ROLES)
    item = db.menu_items.get(itemId)
    if item is None:
        not_found("MenuItem not found")
    return success_object(ser_item(item))


@catalog_bp.route("/menu-items/<itemId>/retire", methods=["POST"])
def retire_menu_item(itemId):
    require_auth(["PlatformAdmin"])
    item = db.menu_items.get(itemId)
    if item is None:
        not_found("MenuItem not found")
    item["status"] = "RETIRED"
    touch(item)
    return success_object(ser_item(item))


@catalog_bp.route("/customization-options", methods=["POST"])
def create_option():
    require_auth(["PlatformAdmin"])
    body = body_json()
    code = get_str(body, "code", required=True)
    applies = get_enum(body, "applies_to_category", APPLIES_TO, required=True)
    price = get_int(body, "price_cents", required=True, minimum=0)
    is_size = get_bool(body, "is_size", default=False)
    upcharge = get_int(body, "size_upcharge_cents", default=0, minimum=0)
    rec = make_record()
    rec.update(
        {
            "code": code,
            "applies_to_category": applies,
            "price_cents": price,
            "is_size": is_size,
            "size_upcharge_cents": upcharge,
            "status": "ACTIVE",
        }
    )
    db.customization_options[rec["id"]] = rec
    return success_object(ser_option(rec), 201)


@catalog_bp.route("/customization-options", methods=["GET"])
def list_options():
    require_auth(ALL_READ_ROLES)
    from flask import request

    status = request.args.get("status")
    if status is not None and status not in ("ACTIVE", "RETIRED"):
        from errors import invalid_request

        invalid_request("status must be ACTIVE or RETIRED")
    opts = list(db.customization_options.values())
    if status is not None:
        opts = [o for o in opts if o["status"] == status]
    opts = sort_by_created(opts)
    limit, offset = pagination_params()
    total = len(opts)
    page = opts[offset : offset + limit]
    return success_array([ser_option(o) for o in page], limit, offset, total)

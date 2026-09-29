"""Menu items: plate costing, activation and the item's mix history (PRD 3.5)."""
from flask import Blueprint

import serial
from calc import plate_cost
from core import (
    KIDS_MENU_SODIUM_CAP_MCG, MARGIN_CLASSES, REGIONS, db, order_key,
    stamp_new, touch,
)
from envelope import created, listing, ok
from errors import fail
from graph import mix_lines_of
from guards import (
    ANY_ROLE, authenticate, find_menu_item, find_recipe, get_body, opt_bool,
    pagination, paginate, query_enum, query_str, req_enum, req_id, req_int,
    req_str,
)

bp = Blueprint("menu_items", __name__)

MENU_ITEM_CODE = r"^[A-Z0-9-]{3,20}$"


@bp.post("/culinary/menu-items")
def create_menu_item():
    authenticate(("RecipeDeveloper",))
    body = get_body()
    code = req_str(body, "code", pattern=MENU_ITEM_CODE, min_len=None)
    name = req_str(body, "name", min_len=1, max_len=80)
    recipe_id = req_id(body, "recipe_id")
    region_code = req_enum(body, "region_code", REGIONS)
    current_price_cents = req_int(body, "current_price_cents", minimum=1)
    target_food_cost_bps = req_int(body, "target_food_cost_bps", minimum=500,
                                   maximum=9000)
    declared_allergen_mask = req_int(body, "declared_allergen_mask", minimum=0,
                                     maximum=255)
    is_kids_menu = opt_bool(body, "is_kids_menu", default=False)

    recipe = find_recipe(recipe_id)
    if recipe["recipe_type"] != "PLATED":
        fail("ERR_INVALID_REQUEST",
             "A menu item may only be created on a PLATED recipe.")
    for existing in db.menu_items.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_CODE", "Menu item code %s already exists." % code)

    row = stamp_new({
        "code": code,
        "name": name,
        "recipe_id": recipe["id"],
        "region_code": region_code,
        "current_price_cents": current_price_cents,
        "target_food_cost_bps": target_food_cost_bps,
        "declared_allergen_mask": declared_allergen_mask,
        "is_kids_menu": is_kids_menu,
        "is_lto": False,
        "open_lto_count": 0,
        "plate_cost_micros": 0,
        "plate_cost_cents": 0,
        "food_cost_bps": 0,
        "contribution_margin_cents": 0,
        "plate_cost_state": "STALE",
        "cost_basis": None,
        "allergen_mask": 0,
        "sodium_mcg_per_portion": 0,
        "margin_class": "UNCLASSIFIED",
        "status": "DRAFT",
        "last_price_change_at": None,
    })
    db.menu_items[row["id"]] = row
    return created(serial.menu_item(row))


@bp.get("/culinary/menu-items/<menu_item_id>")
def get_menu_item(menu_item_id):
    authenticate(ANY_ROLE)
    return ok(serial.menu_item(find_menu_item(menu_item_id)))


@bp.get("/culinary/menu-items")
def list_menu_items():
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", ("DRAFT", "ACTIVE", "SUSPENDED", "RETIRED"))
    margin_class = query_enum("margin_class", MARGIN_CLASSES)
    region_code = query_enum("region_code", REGIONS)
    recipe_id = query_str("recipe_id")
    rows = list(db.menu_items.values())
    if recipe_id is not None:
        rows = [m for m in rows if m["recipe_id"] == recipe_id]
    if region_code is not None:
        rows = [m for m in rows if m["region_code"] == region_code]
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    if margin_class is not None:
        rows = [m for m in rows if m["margin_class"] == margin_class]
    rows.sort(key=order_key)
    page, limit, offset, total = paginate(rows, limit, offset, serial.menu_item)
    return listing(page, limit, offset, total)


@bp.post("/culinary/menu-items/<menu_item_id>/plate-cost")
def compute_plate_cost(menu_item_id):
    authenticate(("CostAnalyst",))
    item = find_menu_item(menu_item_id)
    recipe = db.recipes.get(item["recipe_id"])
    if recipe is None:
        fail("ERR_RECIPE_NOT_FOUND", "The backing recipe no longer exists.")
    if recipe["cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The backing recipe's cost is STALE.")
    plate_cost(item, recipe)
    return ok(serial.menu_item(item))


@bp.post("/culinary/menu-items/<menu_item_id>/activate")
def activate_menu_item(menu_item_id):
    authenticate(("CulinaryDirector",))
    item = find_menu_item(menu_item_id)
    recipe = db.recipes.get(item["recipe_id"])
    if recipe is None:
        fail("ERR_RECIPE_NOT_FOUND", "The backing recipe no longer exists.")
    # 18 -- the backing recipe first.
    if recipe["status"] != "ACTIVE":
        fail("ERR_RECIPE_INVALID_STATE", "The backing recipe is not ACTIVE.")
    # 20 -- the item's own status.
    if item["status"] not in ("DRAFT", "SUSPENDED"):
        fail("ERR_MENU_ITEM_INVALID_STATE",
             "Only a DRAFT or SUSPENDED menu item can be activated.")
    # 26 -- the plate cost must be known.
    if item["plate_cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The menu item's plate cost is STALE.")
    # 32 -- the declared mask must cover the recipe's rolled-up mask.
    if recipe["allergen_mask"] & ~item["declared_allergen_mask"]:
        fail("ERR_ALLERGEN_UNDECLARED",
             "The declared allergen mask does not cover the recipe's allergen mask.")
    # 33 -- the kids-menu sodium ceiling.
    if item["is_kids_menu"] and recipe["sodium_mcg_per_portion"] > KIDS_MENU_SODIUM_CAP_MCG:
        fail("ERR_NUTRITION_LIMIT_EXCEEDED",
             "A kids-menu item may not exceed %d micrograms of sodium per portion."
             % KIDS_MENU_SODIUM_CAP_MCG)
    item["status"] = "ACTIVE"
    touch(item)
    return ok(serial.menu_item(item))


@bp.get("/culinary/menu-items/<menu_item_id>/mix-lines")
def list_item_mix_lines(menu_item_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    find_menu_item(menu_item_id)
    rows = []
    for review in db.period_reviews.values():
        for line in mix_lines_of(review["id"]):
            if line["menu_item_id"] == menu_item_id:
                rows.append((review, line))
    # Newest review first: period_end DESC, then the review's own created_at ASC,
    # then the line's created_at ASC inside one review.
    rows.sort(key=lambda pair: (order_key(pair[0]), order_key(pair[1])))
    rows.sort(key=lambda pair: pair[0]["period_end"], reverse=True)
    page, limit, offset, total = paginate([pair[1] for pair in rows], limit, offset,
                                         serial.mix_line)
    return listing(page, limit, offset, total)

"""Sites, food types, recipes and haulers."""
from flask import Blueprint

from db import base_row, db, touch
from errors import fail
from middleware import (ALL_READERS, CORPORATE_LEAD, HAULER_READERS,
                        PLATFORM_ADMIN, authenticate)
from response import row_response
from routes.common import filtered, must_exist, respond_list
from services import calc
from services.calc import num
from validation import (body_json, field_array, field_bool, field_decimal,
                       field_enum, field_int, field_object_array, field_str,
                       query_bool, query_enum, query_str, bad)

bp = Blueprint("catalog", __name__)

CATEGORIES = ("PRODUCE", "PROTEIN", "PREPARED", "BAKERY", "DAIRY")
POSTURES = ("MONITORING", "INTERVENTION", "ESCALATED")
CHANNELS = ("DONATION", "ANIMAL_FEED", "COMPOST", "LANDFILL")


# ------------------------------------------------------------------- sites
@bp.route("/sites", methods=["POST"])
def create_site():
    authenticate((PLATFORM_ADMIN,))
    body = body_json()
    name = field_str(body, "name")
    site_code = field_str(body, "site_code", min_len=2, max_len=12)
    region_code = field_str(body, "region_code")
    target = field_decimal(body, "target_intensity_kg_per_1k_meals",
                           required=False, exclusive_min=0, scale=3,
                           default=calc.DEFAULT_TARGET_INTENSITY)
    for row in db.sites.values():
        if row["site_code"] == site_code:
            fail("ERR_DUPLICATE_SITE_CODE", "site_code is already in use.")
    site = base_row(
        name=name,
        site_code=site_code,
        region_code=region_code,
        target_intensity_kg_per_1k_meals=num(target),
        total_captured_weight_grams=0,
        valued_waste_cost_cents=0,
        diverted_weight_grams_settled=0,
        diversion_rate_pct=None,
        open_alert_count=0,
        coaching_posture="MONITORING",
    )
    db.sites[site["id"]] = site
    return row_response(site, 201)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND"))


@bp.route("/sites", methods=["GET"])
def list_sites():
    authenticate(ALL_READERS)
    rows = filtered(list(db.sites.values()),
                    region_code=query_str("region_code"),
                    coaching_posture=query_enum("coaching_posture", POSTURES))
    return respond_list(rows)


# -------------------------------------------------------------- food types
@bp.route("/food-types", methods=["POST"])
def create_food_type():
    authenticate((PLATFORM_ADMIN,))
    body = body_json()
    name = field_str(body, "name")
    category = field_enum(body, "category", CATEGORIES)
    cost = field_int(body, "default_cost_per_kg_cents", minimum=1)
    donation_eligible = field_bool(body, "donation_eligible")
    animal_feed_eligible = field_bool(body, "animal_feed_eligible")
    compostable = field_bool(body, "compostable")
    shelf_life = field_int(body, "donation_shelf_life_hours", required=False,
                           minimum=0, default=0)
    for row in db.food_types.values():
        if row["name"] == name:
            fail("ERR_DUPLICATE_FOOD_TYPE_NAME", "name is already in use.")
    food_type = base_row(
        name=name,
        category=category,
        default_cost_per_kg_cents=cost,
        donation_eligible=donation_eligible,
        animal_feed_eligible=animal_feed_eligible,
        compostable=compostable,
        donation_shelf_life_hours=shelf_life,
    )
    db.food_types[food_type["id"]] = food_type
    return row_response(food_type, 201)


@bp.route("/food-types/<food_type_id>", methods=["GET"])
def get_food_type(food_type_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.food_types, food_type_id,
                                   "ERR_FOOD_TYPE_NOT_FOUND"))


@bp.route("/food-types", methods=["GET"])
def list_food_types():
    authenticate(ALL_READERS)
    rows = filtered(list(db.food_types.values()),
                    category=query_enum("category", CATEGORIES),
                    donation_eligible=query_bool("donation_eligible"),
                    animal_feed_eligible=query_bool("animal_feed_eligible"))
    return respond_list(rows)


# ----------------------------------------------------------------- recipes
def _read_ingredients(body):
    items = field_object_array(body, "ingredients", required=True, min_len=1)
    parsed = []
    for index, item in enumerate(items):
        name = field_str(item, "ingredient_name")
        quantity = field_decimal(item, "quantity_kg", exclusive_min=0)
        unit_cost = field_int(item, "unit_cost_cents_per_kg", minimum=1)
        trim = field_decimal(item, "trim_loss_pct", minimum=0, exclusive_max=1)
        parsed.append({
            "ingredient_name": name,
            "quantity_kg": num(quantity),
            "unit_cost_cents_per_kg": unit_cost,
            "trim_loss_pct": num(trim),
        })
    return parsed


def _apply_recipe_costs(recipe):
    total, usable, per_kg = calc.recipe_cost(recipe["ingredients"])
    recipe["total_ingredient_cost_cents"] = total
    recipe["usable_yield_kg"] = num(usable)
    recipe["cost_per_kg_cents"] = per_kg
    return recipe


@bp.route("/recipes", methods=["POST"])
def create_recipe():
    authenticate((PLATFORM_ADMIN,))
    body = body_json()
    recipe_code = field_str(body, "recipe_code")
    name = field_str(body, "name")
    ingredients = _read_ingredients(body)
    for row in db.recipes.values():
        if row["recipe_code"] == recipe_code:
            fail("ERR_DUPLICATE_RECIPE_CODE", "recipe_code is already in use.")
    recipe = base_row(
        recipe_code=recipe_code,
        name=name,
        ingredients=ingredients,
        status="DRAFT",
        total_ingredient_cost_cents=0,
        usable_yield_kg=0.0,
        cost_per_kg_cents=None,
        published_cost_per_kg_cents=None,
        published_at=None,
    )
    _apply_recipe_costs(recipe)
    db.recipes[recipe["id"]] = recipe
    return row_response(recipe, 201)


@bp.route("/recipes/<recipe_id>/publish", methods=["POST"])
def publish_recipe(recipe_id):
    authenticate((PLATFORM_ADMIN,))
    body_json()
    recipe = must_exist(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    if recipe["status"] != "DRAFT":
        fail("ERR_INVALID_RECIPE_STATE", "Only a DRAFT recipe may be published.")
    if not recipe["ingredients"]:
        bad("A recipe must hold at least one ingredient to be published.")
    _apply_recipe_costs(recipe)
    recipe["published_cost_per_kg_cents"] = recipe["cost_per_kg_cents"]
    recipe["published_at"] = db.now_iso()
    recipe["status"] = "PUBLISHED"
    touch(recipe)
    return row_response(recipe)


@bp.route("/recipes/<recipe_id>", methods=["GET"])
def get_recipe(recipe_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND"))


@bp.route("/recipes", methods=["GET"])
def list_recipes():
    authenticate(ALL_READERS)
    rows = filtered(list(db.recipes.values()),
                    status=query_enum("status", ("DRAFT", "PUBLISHED")))
    return respond_list(rows)


# ----------------------------------------------------------------- haulers
@bp.route("/haulers", methods=["POST"])
def create_hauler():
    authenticate((PLATFORM_ADMIN,))
    body = body_json()
    name = field_str(body, "name")
    channels = field_array(body, "channels", min_len=1)
    for channel in channels:
        if not isinstance(channel, str) or channel not in CHANNELS:
            bad("Every member of 'channels' must be one of %s."
                % ", ".join(CHANNELS))
    if len(set(channels)) != len(channels):
        bad("'channels' must not contain duplicates.")
    rate = field_int(body, "rate_cents_per_tonne", minimum=1)
    stop_fee = field_int(body, "stop_fee_cents", minimum=0)
    capacity = field_decimal(body, "capacity_kg_per_pickup", exclusive_min=0)
    concurrent = field_int(body, "max_concurrent_pickups", required=False,
                           minimum=1, default=1)
    for row in db.haulers.values():
        if row["name"] == name:
            fail("ERR_DUPLICATE_HAULER_NAME", "name is already in use.")
    hauler = base_row(
        name=name,
        channels=list(channels),
        rate_cents_per_tonne=rate,
        stop_fee_cents=stop_fee,
        capacity_kg_per_pickup=num(capacity),
        max_concurrent_pickups=concurrent,
        status="PENDING",
    )
    db.haulers[hauler["id"]] = hauler
    return row_response(hauler, 201)


@bp.route("/haulers/<hauler_id>/approve", methods=["POST"])
def approve_hauler(hauler_id):
    authenticate((CORPORATE_LEAD,))
    body_json()
    hauler = must_exist(db.haulers, hauler_id, "ERR_HAULER_NOT_FOUND")
    if hauler["status"] != "PENDING":
        fail("ERR_INVALID_HAULER_STATE", "The hauler is already approved.")
    hauler["status"] = "APPROVED"
    touch(hauler)
    return row_response(hauler)


@bp.route("/haulers/<hauler_id>", methods=["GET"])
def get_hauler(hauler_id):
    authenticate(HAULER_READERS)
    return row_response(must_exist(db.haulers, hauler_id, "ERR_HAULER_NOT_FOUND"))


@bp.route("/haulers", methods=["GET"])
def list_haulers():
    authenticate(HAULER_READERS)
    rows = filtered(list(db.haulers.values()),
                    status=query_enum("status", ("PENDING", "APPROVED")))
    channel = query_enum("channel", CHANNELS)
    if channel is not None:
        rows = [r for r in rows if channel in r["channels"]]
    return respond_list(rows)

"""The therapeutic rule catalogue and the menu (PRD section 3.2)."""

from flask import Blueprint

import api
import serialize
import store
from calcs import LIQUID_LEVELS, TEXTURE_LEVELS
from errors import ApiError

rules_bp = Blueprint("diet_rules", __name__, url_prefix="/nutrition/diet-rules")
items_bp = Blueprint("menu_items", __name__, url_prefix="/nutrition/menu-items")

RULE_STATUSES = ("ACTIVE", "RETIRED")
ITEM_STATUSES = ("ACTIVE", "DISCONTINUED")
TEMP_CLASSES = ("HOT", "COLD", "AMBIENT")


# ---------------------------------------------------------------------------
# Therapeutic diet rules
# ---------------------------------------------------------------------------
@rules_bp.post("")
@api.require("Dietitian", "NutritionManager")
def create_rule():
    body = api.body()
    diet_code = api.req_str(body, "diet_code")
    display_name = api.req_str(body, "display_name")
    precedence_rank = api.req_int(body, "precedence_rank", lo=1, hi=999)
    max_sodium = api.opt_int(body, "max_sodium_mg_per_meal", None, lo=0)
    max_potassium = api.opt_int(body, "max_potassium_mg_per_meal", None, lo=0)
    max_carb = api.opt_num(body, "max_carb_g_per_meal", None, lo=0)
    min_texture = api.opt_enum(body, "min_texture_level", TEXTURE_LEVELS,
                               None, nullable=True)
    min_liquid = api.opt_enum(body, "min_liquid_level", LIQUID_LEVELS,
                              None, nullable=True)
    forbidden = api.opt_str_list(body, "forbidden_tag_codes", [])
    requires_cosign = api.opt_bool(body, "requires_dietitian_cosign", True)

    if any(r["diet_code"] == diet_code for r in store.diet_rules.values()):
        raise ApiError("ERR_DUPLICATE_DIET_RULE_CODE",
                       "A diet rule with code '%s' already exists." % diet_code)

    rule = {
        "diet_code": diet_code,
        "display_name": display_name,
        "max_sodium_mg_per_meal": max_sodium,
        "max_potassium_mg_per_meal": max_potassium,
        "max_carb_g_per_meal": max_carb,
        "min_texture_level": min_texture,
        "min_liquid_level": min_liquid,
        "forbidden_tag_codes": forbidden,
        "requires_dietitian_cosign": requires_cosign,
        "precedence_rank": precedence_rank,
        "status": "ACTIVE",
    }
    store.stamp_new(rule)
    store.diet_rules[rule["id"]] = rule
    return api.created(serialize.diet_rule(rule))


@rules_bp.get("")
@api.require(*api.ALL_ROLES)
def list_rules():
    status = api.q_enum("status", RULE_STATUSES)
    rows = api.filtered(list(store.diet_rules.values()), [(status, "status")])
    return api.paged(rows, serialize.diet_rule)


@rules_bp.get("/<rule_id>")
@api.require(*api.ALL_ROLES)
def read_rule(rule_id):
    return api.ok(serialize.diet_rule(store.get_diet_rule(rule_id)))


@rules_bp.patch("/<rule_id>")
@api.require("Dietitian", "NutritionManager")
def update_rule(rule_id):
    rule = store.get_diet_rule(rule_id)
    body = api.body()
    status = api.opt_enum(body, "status", RULE_STATUSES)
    if status is not None and status == rule["status"]:
        raise ApiError("ERR_INVALID_STATE", "The rule is already %s." % rule["status"])
    if status is not None:
        rule["status"] = status
    store.touch(rule)
    return api.ok(serialize.diet_rule(rule))


# ---------------------------------------------------------------------------
# Menu items
# ---------------------------------------------------------------------------
@items_bp.post("")
@api.require("NutritionManager")
def create_item():
    body = api.body()
    item_code = api.req_str(body, "item_code")
    display_name = api.req_str(body, "display_name")
    sodium = api.req_int(body, "sodium_mg", lo=0)
    potassium = api.req_int(body, "potassium_mg", lo=0)
    carb = api.req_num(body, "carb_g", lo=0)
    protein = api.req_num(body, "protein_g", lo=0)
    unit_cost = api.req_int(body, "unit_cost_cents", lo=0)
    texture = api.req_enum(body, "texture_level", TEXTURE_LEVELS)
    temp_class = api.req_enum(body, "service_temp_class", TEMP_CLASSES)
    liquid = api.opt_enum(body, "liquid_level", LIQUID_LEVELS, None, nullable=True)
    allergens = api.opt_str_list(body, "allergen_codes", [])
    tags = api.opt_str_list(body, "tag_codes", [])

    if any(i["item_code"] == item_code for i in store.menu_items.values()):
        raise ApiError("ERR_DUPLICATE_MENU_ITEM_CODE",
                       "A menu item with code '%s' already exists." % item_code)

    item = {
        "item_code": item_code,
        "display_name": display_name,
        "sodium_mg": sodium,
        "potassium_mg": potassium,
        "carb_g": carb,
        "protein_g": protein,
        "unit_cost_cents": unit_cost,
        "texture_level": texture,
        "liquid_level": liquid,
        "service_temp_class": temp_class,
        "allergen_codes": allergens,
        "tag_codes": tags,
        "status": "ACTIVE",
    }
    store.stamp_new(item)
    store.menu_items[item["id"]] = item
    return api.created(serialize.menu_item(item))


@items_bp.get("")
@api.require(*api.ALL_ROLES)
def list_items():
    status = api.q_enum("status", ITEM_STATUSES)
    texture = api.q_enum("texture_level", TEXTURE_LEVELS)
    temp_class = api.q_enum("service_temp_class", TEMP_CLASSES)
    rows = api.filtered(list(store.menu_items.values()),
                        [(status, "status"), (texture, "texture_level"),
                         (temp_class, "service_temp_class")])
    return api.paged(rows, serialize.menu_item)


@items_bp.get("/<item_id>")
@api.require(*api.ALL_ROLES)
def read_item(item_id):
    return api.ok(serialize.menu_item(store.get_menu_item(item_id)))


@items_bp.patch("/<item_id>")
@api.require("NutritionManager")
def update_item(item_id):
    item = store.get_menu_item(item_id)
    body = api.body()
    status = api.opt_enum(body, "status", ITEM_STATUSES)
    unit_cost = api.opt_int(body, "unit_cost_cents", None, lo=0)
    if status is not None and status == item["status"]:
        raise ApiError("ERR_INVALID_STATE", "The menu item is already %s." % item["status"])
    if status is not None:
        item["status"] = status
    if unit_cost is not None:
        item["unit_cost_cents"] = unit_cost
    store.touch(item)
    return api.ok(serialize.menu_item(item))

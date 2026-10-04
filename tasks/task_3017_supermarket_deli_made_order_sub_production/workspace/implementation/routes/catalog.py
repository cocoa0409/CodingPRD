"""DeliItem catalog group and its usage reverse-reads."""
from errors import fail, invalid
from http_support import (
    Endpoint, as_bool, as_int, as_list, as_string, body, envelope_array, opt,
    query, req,
)
from response import ok_object
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
WRITE_ROLES = ["PlatformAdmin", "DeliManager"]

CATEGORIES = ("HOT_BAR", "COLD_CUT", "ROTISSERIE", "SUB", "BREAD",
              "CATERING_PLATTER")
ALLERGENS = ("MILK", "WHEAT", "SOY", "EGG", "FISH", "SESAME")
STATUSES = ("ACTIVE", "DISCONTINUED")


def register(app):
    Endpoint(app, "POST", "/deli/items", WRITE_ROLES, create_item)
    Endpoint(app, "GET", "/deli/items/<id>", READ_ROLES, get_item)
    Endpoint(app, "GET", "/deli/items", READ_ROLES, list_items)
    Endpoint(app, "PATCH", "/deli/items/<id>", WRITE_ROLES, patch_item)
    Endpoint(app, "GET", "/deli/items/<id>/slicer-usage", READ_ROLES, slicer_usage)
    Endpoint(app, "GET", "/deli/items/<id>/sanitation-usage", READ_ROLES,
             sanitation_usage)
    Endpoint(app, "GET", "/deli/items/<id>/certification-usage", READ_ROLES,
             certification_usage)


def create_item(store, actor, view_args):
    payload = body()
    sku = as_string(req(payload, "sku"), "sku")
    if any(i["sku"] == sku for i in store.items.values()):
        invalid("sku must be unique across the chain.")
    name = as_string(req(payload, "name"), "name")
    category = req(payload, "category")
    if category not in CATEGORIES:
        invalid("category must be one of %s." % ", ".join(CATEGORIES))
    unit_cost = as_int(req(payload, "unit_cost_cents"), "unit_cost_cents")
    retail = as_int(req(payload, "retail_price_per_lb_cents"),
                    "retail_price_per_lb_cents")
    if unit_cost < 0 or retail < 0:
        invalid("cents fields must not be negative.")
    case_life = as_int(req(payload, "case_life_minutes"), "case_life_minutes")
    markdown_window = as_int(req(payload, "markdown_window_minutes"),
                             "markdown_window_minutes")
    if case_life <= 0:
        invalid("case_life_minutes must be greater than 0.")
    if markdown_window < 0 or markdown_window > case_life:
        invalid("markdown_window_minutes must be between 0 and case_life_minutes.")
    allergens = as_list(req(payload, "allergen_flags"), "allergen_flags")
    for flag in allergens:
        if flag not in ALLERGENS:
            invalid("allergen_flags must be drawn from %s." % ", ".join(ALLERGENS))

    bread_id = opt(payload, "bread_deli_item_id")
    if category == "SUB":
        if bread_id is None:
            invalid("a SUB item must name the bread_deli_item_id it is served on.")
        bread = store.items.get(bread_id)
        if bread is None or bread["category"] != "BREAD":
            invalid("bread_deli_item_id must reference a BREAD catalog item.")
    elif bread_id is not None:
        invalid("bread_deli_item_id is only valid for SUB items.")

    servings = as_int(opt(payload, "servings_per_platter", default=12),
                      "servings_per_platter")
    row = svc.create(store, "items", {
        "sku": sku,
        "name": name,
        "category": category,
        "unit_cost_cents": unit_cost,
        "retail_price_per_lb_cents": retail,
        "case_life_minutes": case_life,
        "markdown_window_minutes": markdown_window,
        "allergen_flags": list(allergens),
        "slicer_required": as_bool(req(payload, "slicer_required"), "slicer_required"),
        "servings_per_platter": servings,
        "bread_deli_item_id": bread_id,
        "status": "ACTIVE",
    })
    return ok_object(store, views.deli_item(row), 201)


def get_item(store, actor, view_args):
    row = svc.get_plain(store, "items", view_args["id"])
    return ok_object(store, views.deli_item(row))


def list_items(store, actor, view_args):
    rows = svc.all_rows(store, "items")
    # Discontinued rows are suppressed unless include_discontinued is set.
    if not _flag(query("include_discontinued")):
        rows = [r for r in rows if r["status"] != "DISCONTINUED"]
    category = query("category")
    bread_id = query("bread_deli_item_id")
    if category:
        rows = [r for r in rows if r["category"] == category]
    if bread_id:
        rows = [r for r in rows if r["bread_deli_item_id"] == bread_id]
    return envelope_array(store, rows, views.deli_item)


def _flag(raw):
    if raw is None:
        return False
    return str(raw).lower() in ("1", "true", "yes")


def patch_item(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "items", view_args["id"])
    svc.check_occ(store, row, opt(payload, "expected_item_version"),
                  "expected_item_version")
    if "retail_price_per_lb_cents" in payload:
        value = as_int(payload["retail_price_per_lb_cents"], "retail_price_per_lb_cents")
        if value < 0:
            invalid("retail_price_per_lb_cents must not be negative.")
        row["retail_price_per_lb_cents"] = value
    if "unit_cost_cents" in payload:
        value = as_int(payload["unit_cost_cents"], "unit_cost_cents")
        if value < 0:
            invalid("unit_cost_cents must not be negative.")
        row["unit_cost_cents"] = value
    if "case_life_minutes" in payload:
        value = as_int(payload["case_life_minutes"], "case_life_minutes")
        if value <= 0:
            invalid("case_life_minutes must be greater than 0.")
        row["case_life_minutes"] = value
    if "markdown_window_minutes" in payload:
        value = as_int(payload["markdown_window_minutes"], "markdown_window_minutes")
        if value < 0 or value > row["case_life_minutes"]:
            invalid("markdown_window_minutes must be between 0 and case_life_minutes.")
        row["markdown_window_minutes"] = value
    if "status" in payload:
        status = payload["status"]
        if status not in STATUSES:
            invalid("status must be one of %s." % ", ".join(STATUSES))
        row["status"] = status
    svc.touch(store, row)
    for store_row in svc.all_rows(store, "stores"):
        svc.recompute_store(store, store_row["id"])
    return ok_object(store, views.deli_item(row))


def slicer_usage(store, actor, view_args):
    item = svc.get_plain(store, "items", view_args["id"])
    rows = [s for s in svc.all_rows(store, "slicers")
            if s["last_sliced_deli_item_id"] == item["id"]]
    return envelope_array(store, rows, views.slicer)


def sanitation_usage(store, actor, view_args):
    item = svc.get_plain(store, "items", view_args["id"])
    rows = [c for c in svc.all_rows(store, "sanitation_cycles")
            if c["allergen_cleared_from_item_id"] == item["id"]]
    return envelope_array(store, rows, views.cycle)


def certification_usage(store, actor, view_args):
    item = svc.get_plain(store, "items", view_args["id"])
    rows = [c for c in svc.all_rows(store, "certifications")
            if c["deli_item_id"] == item["id"]]
    return envelope_array(store, rows, views.certification)
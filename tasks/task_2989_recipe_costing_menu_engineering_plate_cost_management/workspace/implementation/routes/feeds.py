"""Distributor price feeds and the five-hop publication cascade (PRD 3.2)."""
from flask import Blueprint

import serial
from cascade import propagate_upward, stale_menu_items_of
from core import DISTRIBUTORS, REGIONS, db, order_key, stamp_new, touch
from envelope import created, listing, ok
from errors import fail
from graph import active_components
from guards import (
    ANY_ROLE, authenticate, find_feed, find_ingredient, get_body, opt_instant,
    pagination, paginate, query_enum, req_enum, req_id, req_instant, req_int,
)

bp = Blueprint("feeds", __name__)


def _feed_lines(price_feed_id):
    rows = [p for p in db.ingredient_prices.values()
            if p["price_feed_id"] == price_feed_id]
    return sorted(rows, key=order_key)


@bp.post("/culinary/price-feeds")
def create_feed():
    authenticate(("CostAnalyst",))
    body = get_body()
    distributor_code = req_enum(body, "distributor_code", DISTRIBUTORS)
    region_code = req_enum(body, "region_code", REGIONS)
    feed_date = req_instant(body, "feed_date")
    row = stamp_new({
        "distributor_code": distributor_code,
        "region_code": region_code,
        "feed_date": feed_date,
        "status": "DRAFT",
        "line_count": 0,
        "published_at": None,
        "superseded_price_count": 0,
        "affected_recipe_count": 0,
        "affected_menu_item_count": 0,
    })
    db.price_feeds[row["id"]] = row
    return created(serial.price_feed(row))


@bp.get("/culinary/price-feeds/<price_feed_id>")
def get_feed(price_feed_id):
    authenticate(ANY_ROLE)
    return ok(serial.price_feed(find_feed(price_feed_id)))


@bp.post("/culinary/price-feeds/<price_feed_id>/lines")
def create_feed_line(price_feed_id):
    authenticate(("CostAnalyst",))
    body = get_body()
    ingredient_id = req_id(body, "ingredient_id")
    pack_cost_micros = req_int(body, "pack_cost_micros", minimum=1)
    effective_from = req_instant(body, "effective_from")
    effective_to = opt_instant(body, "effective_to")
    feed = find_feed(price_feed_id)
    ingredient = find_ingredient(ingredient_id)
    if feed["status"] != "DRAFT":
        fail("ERR_FEED_ALREADY_PUBLISHED", "The feed is already PUBLISHED.")
    row = stamp_new({
        "ingredient_id": ingredient_id,
        "price_feed_id": feed["id"],
        "region_code": feed["region_code"],
        "distributor_code": feed["distributor_code"],
        "pack_cost_micros": pack_cost_micros,
        "pack_base_units_snapshot": ingredient["pack_base_units"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "PENDING",
    })
    db.ingredient_prices[row["id"]] = row
    feed["line_count"] = len(_feed_lines(feed["id"]))
    touch(feed)
    return created(serial.ingredient_price(row))


@bp.get("/culinary/price-feeds/<price_feed_id>/lines")
def list_feed_lines(price_feed_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", ("PENDING", "PUBLISHED", "SUPERSEDED"))
    find_feed(price_feed_id)
    rows = _feed_lines(price_feed_id)
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, limit, offset, total = paginate(rows, limit, offset, serial.ingredient_price)
    return listing(page, limit, offset, total)


@bp.post("/culinary/price-feeds/<price_feed_id>/publish")
def publish_feed(price_feed_id):
    authenticate(("CostAnalyst",))
    feed = find_feed(price_feed_id)
    lines = _feed_lines(price_feed_id)

    # 19 -- still DRAFT and holding at least one line.
    if feed["status"] != "DRAFT":
        fail("ERR_FEED_ALREADY_PUBLISHED", "The feed is already PUBLISHED.")
    if not lines:
        fail("ERR_FEED_ALREADY_PUBLISHED", "An empty feed cannot be published.")

    # 31 -- every quoted ingredient must still be ACTIVE.
    for line in lines:
        ingredient = db.ingredients.get(line["ingredient_id"])
        if ingredient is None or ingredient["status"] != "ACTIVE":
            fail("ERR_INGREDIENT_RETIRED",
                 "Line quotes retired ingredient %s." % line["ingredient_id"])

    # 45 -- no collision with a window already in force.
    for line in lines:
        for other in db.ingredient_prices.values():
            if other["status"] != "PUBLISHED":
                continue
            if other["price_feed_id"] == feed["id"]:
                continue
            if (other["ingredient_id"] != line["ingredient_id"]
                    or other["region_code"] != line["region_code"]):
                continue
            if line["effective_from"] <= other["effective_from"]:
                fail("ERR_PRICE_WINDOW_OVERLAP",
                     "A published price window already covers this ingredient and region.")
            if (other["effective_to"] is not None
                    and line["effective_from"] < other["effective_to"]):
                fail("ERR_PRICE_WINDOW_OVERLAP",
                     "A published price window already covers this ingredient and region.")

    # --- Hop 1: the feed and its lines, plus the truncation of predecessors.
    now = db.now()
    feed["status"] = "PUBLISHED"
    feed["published_at"] = now
    superseded = 0
    for line in lines:
        for other in list(db.ingredient_prices.values()):
            if other["status"] != "PUBLISHED":
                continue
            if other["price_feed_id"] == feed["id"]:
                continue
            if (other["ingredient_id"] != line["ingredient_id"]
                    or other["region_code"] != line["region_code"]):
                continue
            if other["effective_to"] is not None:
                continue
            if other["effective_from"] >= line["effective_from"]:
                continue
            other["effective_to"] = line["effective_from"]
            other["status"] = "SUPERSEDED"
            touch(other)
            superseded += 1
        line["status"] = "PUBLISHED"
        touch(line)
    feed["superseded_price_count"] = superseded

    # --- Hop 2: recipes consuming a newly priced ingredient.
    priced = set(line["ingredient_id"] for line in lines)
    directly_staled = []
    for recipe in sorted(db.recipes.values(), key=order_key):
        if recipe["cost_state"] != "FRESH":
            continue
        for component in active_components(recipe["id"]):
            if (component["component_type"] == "INGREDIENT"
                    and component["ingredient_id"] in priced):
                recipe["cost_state"] = "STALE"
                touch(recipe)
                directly_staled.append(recipe["id"])
                break

    # --- Hop 3: transitive parents.
    ancestors = propagate_upward(directly_staled)
    feed["affected_recipe_count"] = len(directly_staled) + len(ancestors)

    # --- Hops 4 and 5: menu items and their margin classes.
    feed["affected_menu_item_count"] = stale_menu_items_of(directly_staled + ancestors)

    touch(feed)
    return ok(serial.price_feed(feed))

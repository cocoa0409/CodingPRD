"""Donated items: list/read, price-point assignment, retail sale."""
from flask import Blueprint, request

import errors
from clock import COLORS, now, week_index
from db import store
from envelope import success
from serializers import ser_item
from services import (
    active_standard_for,
    org_of_item,
    recompute_margin_health,
    touch,
    unit_cost,
)
from validate import auth, get_body, paginate, require_role, sort_created

bp = Blueprint("items", __name__)


@bp.get("/donated-goods/donated-items")
def list_items():
    auth()
    items = list(store.donated_items.values())
    for param in ("donation_id", "salvage_lot_id", "status", "color_tag",
                  "priced_standard_id"):
        val = request.args.get(param)
        if val is not None:
            items = [it for it in items if it[param] == val]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_item(it) for it in page], 200,
                   response_type="array", pagination=meta)


def _get_item(iid):
    item = store.donated_items.get(iid)
    if item is None:
        errors.not_found("DonatedItem not found")
    return item


@bp.get("/donated-goods/donated-items/<iid>")
def get_item(iid):
    auth()
    return success(ser_item(_get_item(iid)), 200)


@bp.post("/donated-goods/donated-items/<iid>/price")
def price_item(iid):
    get_body()
    _uid, role = auth()
    require_role(role, {"StoreAssociate"})
    item = _get_item(iid)
    org = org_of_item(item)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if item["status"] != "SORTED":
        errors.invalid_state("Only a SORTED item can be priced onto the floor")
    std = active_standard_for(org["id"], item["category"])
    if std is None:
        errors.no_eligible_standard()
    with store.lock:
        price = max(
            std["price_floor_cents"],
            min(std["price_ceiling_cents"],
                std["grade_price_map"][item["condition_grade"]]),
        )
        w = week_index()
        item["price_cents"] = price
        item["priced_standard_id"] = std["id"]  # version pinning
        item["unit_cost_cents"] = unit_cost(org, item["category"], std)
        item["floor_week"] = w
        item["color_tag"] = COLORS[w % 4]
        item["markdown_step"] = 0
        item["current_selling_price_cents"] = price
        item["status"] = "ON_FLOOR"
        touch(item)
    return success(ser_item(item), 200)


@bp.post("/donated-goods/donated-items/<iid>/sell")
def sell_item(iid):
    get_body()
    _uid, role = auth()
    require_role(role, {"StoreAssociate"})
    item = _get_item(iid)
    org = org_of_item(item)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if item["status"] != "ON_FLOOR":
        errors.invalid_state("Only an ON_FLOOR item can be sold")
    with store.lock:
        margin = item["current_selling_price_cents"] - item["unit_cost_cents"]
        org["retail_margin_pool_cents"] += margin
        recompute_margin_health(org)
        item["status"] = "SOLD"
        item["sold_at"] = now()
        touch(item)
        touch(org)  # pool mutation advances the org version
    return success(ser_item(item), 200)

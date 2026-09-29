"""Limited-time offers: costing, launch capacity, the post-promotion verdict
and the renew / retire fork (PRD 3.9)."""
from flask import Blueprint

import serial
from calc import lto_costing, lto_post_promo
from core import MAX_CONCURRENT_LTO_PER_REGION, REGIONS, db, order_key, stamp_new, touch
from envelope import created, listing, ok
from errors import fail
from guards import (
    ANY_ROLE, authenticate, find_campaign, find_menu_item, get_body, pagination,
    paginate, query_enum, query_str, req_enum, req_id, req_instant, req_int,
    window,
)

bp = Blueprint("ltos", __name__)

CAMPAIGN_STATUSES = ("PLANNED", "COSTED", "LAUNCHED", "CLOSED", "RENEWED", "RETIRED")


def _blank_campaign(item, window_start, window_end, promo_price_cents, forecast_units):
    return {
        "menu_item_id": item["id"],
        "region_code": item["region_code"],
        "window_start": window_start,
        "window_end": window_end,
        "promo_price_cents": promo_price_cents,
        "forecast_units": forecast_units,
        "status": "PLANNED",
        "promo_plate_cost_cents": 0,
        "promo_food_cost_bps": 0,
        "forecast_contribution_cents": 0,
        "actual_units": 0,
        "actual_gross_sales_cents": 0,
        "promo_support_cost_cents": 0,
        "promo_contribution_cents": 0,
        "forecast_attainment_bps": 0,
        "verdict": "PENDING",
        "reviewed_at": None,
    }


@bp.post("/culinary/lto-campaigns")
def create_campaign():
    authenticate(("RecipeDeveloper",))
    body = get_body()
    menu_item_id = req_id(body, "menu_item_id")
    window_start = req_instant(body, "window_start")
    window_end = req_instant(body, "window_end")
    promo_price_cents = req_int(body, "promo_price_cents", minimum=1)
    forecast_units = req_int(body, "forecast_units", minimum=1)
    expected_menu_item_version = req_int(body, "expected_menu_item_version")
    window(window_start, window_end, "window_start", "window_end")
    item = find_menu_item(menu_item_id)
    # 16 -- planning against a re-priced item is the race worth losing loudly.
    if expected_menu_item_version != item["version"]:
        fail("ERR_STALE_MENU_ITEM_VERSION",
             "expected_menu_item_version %s does not match the stored version %s."
             % (expected_menu_item_version, item["version"]))
    row = stamp_new(_blank_campaign(item, window_start, window_end,
                                   promo_price_cents, forecast_units))
    db.lto_campaigns[row["id"]] = row
    item["open_lto_count"] = item["open_lto_count"] + 1
    touch(item)
    return created(serial.lto_campaign(row))


@bp.get("/culinary/lto-campaigns/<lto_campaign_id>")
def get_campaign(lto_campaign_id):
    authenticate(ANY_ROLE)
    return ok(serial.lto_campaign(find_campaign(lto_campaign_id)))


@bp.get("/culinary/lto-campaigns")
def list_campaigns():
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", CAMPAIGN_STATUSES)
    region_code = query_enum("region_code", REGIONS)
    menu_item_id = query_str("menu_item_id")
    rows = list(db.lto_campaigns.values())
    if menu_item_id is not None:
        rows = [c for c in rows if c["menu_item_id"] == menu_item_id]
    if region_code is not None:
        rows = [c for c in rows if c["region_code"] == region_code]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=order_key)
    rows.sort(key=lambda c: c["window_start"])
    page, limit, offset, total = paginate(rows, limit, offset, serial.lto_campaign)
    return listing(page, limit, offset, total)


@bp.post("/culinary/lto-campaigns/<lto_campaign_id>/cost")
def cost_campaign(lto_campaign_id):
    authenticate(("CostAnalyst",))
    campaign = find_campaign(lto_campaign_id)
    item = db.menu_items.get(campaign["menu_item_id"])
    if item is None:
        fail("ERR_MENU_ITEM_NOT_FOUND", "The promoted menu item no longer exists.")
    # 20 -- the item must be on the menu.
    if item["status"] != "ACTIVE":
        fail("ERR_MENU_ITEM_INVALID_STATE",
             "Only an ACTIVE menu item can carry a costed promotion.")
    # 24 -- the campaign's own status.
    if campaign["status"] != "PLANNED":
        fail("ERR_LTO_INVALID_STATE", "Only a PLANNED campaign can be costed.")
    # 26 -- the plate cost must be known.
    if item["plate_cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The menu item's plate cost is STALE.")
    lto_costing(campaign, item)
    return ok(serial.lto_campaign(campaign))


@bp.post("/culinary/lto-campaigns/<lto_campaign_id>/launch")
def launch_campaign(lto_campaign_id):
    authenticate(("CulinaryDirector",))
    campaign = find_campaign(lto_campaign_id)
    # 24 -- status, and the window must not already have elapsed.
    if campaign["status"] != "COSTED":
        fail("ERR_LTO_INVALID_STATE", "Only a COSTED campaign can be launched.")
    if not db.now() < campaign["window_end"]:
        fail("ERR_LTO_INVALID_STATE",
             "A promotion whose window has elapsed cannot be launched.")
    # 43 -- the per-region ceiling on genuinely overlapping launched promotions.
    overlapping = 0
    for other in db.lto_campaigns.values():
        if other["id"] == campaign["id"] or other["status"] != "LAUNCHED":
            continue
        if other["region_code"] != campaign["region_code"]:
            continue
        if (other["window_start"] < campaign["window_end"]
                and campaign["window_start"] < other["window_end"]):
            overlapping += 1
    if overlapping >= MAX_CONCURRENT_LTO_PER_REGION:
        fail("ERR_LTO_WINDOW_CAPACITY",
             "Region %s already runs %d overlapping launched promotions."
             % (campaign["region_code"], overlapping))
    campaign["status"] = "LAUNCHED"
    touch(campaign)
    item = db.menu_items.get(campaign["menu_item_id"])
    if item is not None:
        item["is_lto"] = True
        touch(item)
    return ok(serial.lto_campaign(campaign))


@bp.post("/culinary/lto-campaigns/<lto_campaign_id>/close-review")
def close_review_campaign(lto_campaign_id):
    authenticate(("CostAnalyst",))
    body = get_body()
    actual_units = req_int(body, "actual_units", minimum=0)
    actual_gross_sales_cents = req_int(body, "actual_gross_sales_cents", minimum=0)
    campaign = find_campaign(lto_campaign_id)
    # 24 -- only a launched promotion is judged.
    if campaign["status"] != "LAUNCHED":
        fail("ERR_LTO_INVALID_STATE", "Only a LAUNCHED campaign can be reviewed.")
    # 44 -- and only after it is over.
    if db.now() < campaign["window_end"]:
        fail("ERR_EFFECTIVE_DATE_NOT_REACHED",
             "The promotion window has not yet closed.")
    lto_post_promo(campaign, actual_units, actual_gross_sales_cents)
    item = db.menu_items.get(campaign["menu_item_id"])
    if item is not None:
        item["is_lto"] = False
        item["open_lto_count"] = max(0, item["open_lto_count"] - 1)
        touch(item)
    return ok(serial.lto_campaign(campaign))


@bp.post("/culinary/lto-campaigns/<lto_campaign_id>/decide")
def decide_campaign(lto_campaign_id):
    authenticate(("CulinaryDirector",))
    body = get_body()
    decision = req_enum(body, "decision", ("RENEW", "RETIRE"))
    campaign = find_campaign(lto_campaign_id)
    # 24 -- status, and the RENEW arm's verdict precondition.
    if campaign["status"] != "CLOSED":
        fail("ERR_LTO_INVALID_STATE", "Only a CLOSED campaign can be decided.")
    if decision == "RENEW" and campaign["verdict"] != "PROFITABLE":
        fail("ERR_LTO_INVALID_STATE",
             "An UNPROFITABLE promotion cannot be renewed.")
    item = db.menu_items.get(campaign["menu_item_id"])
    if item is None:
        fail("ERR_MENU_ITEM_NOT_FOUND", "The promoted menu item no longer exists.")

    if decision == "RENEW":
        campaign["status"] = "RENEWED"
        touch(campaign)
        length = campaign["window_end"] - campaign["window_start"]
        successor = stamp_new(_blank_campaign(
            item, campaign["window_end"], campaign["window_end"] + length,
            campaign["promo_price_cents"], campaign["actual_units"]))
        db.lto_campaigns[successor["id"]] = successor
        item["open_lto_count"] = item["open_lto_count"] + 1
        touch(item)
    else:
        campaign["status"] = "RETIRED"
        touch(campaign)
        item["status"] = "SUSPENDED"
        item["margin_class"] = "UNCLASSIFIED"
        item["is_lto"] = False
        touch(item)
    return ok(serial.lto_campaign(campaign))

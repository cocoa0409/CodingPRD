"""Menu period reviews: sales mix, physical counts, classification and the
theoretical-versus-actual variance (PRD 3.8)."""
from flask import Blueprint

import serial
from calc import classify, close_review
from core import REVIEW_BASES, db, order_key, stamp_new, touch
from envelope import created, listing, ok
from errors import fail
from graph import (
    consuming_recipe_ids, count_lines_of, expected_base_units, mix_lines_of,
)
from guards import (
    ANY_ROLE, authenticate, find_ingredient, find_menu_item, find_review,
    find_unit, get_body, pagination, paginate, query_enum, query_str, req_enum,
    req_id, req_instant, req_int, window,
)

bp = Blueprint("reviews", __name__)

REVIEW_STATUSES = ("OPEN", "MIX_LOADED", "CLASSIFIED", "CLOSED")
LOADABLE_STATUSES = ("OPEN", "MIX_LOADED")


def _recompute_totals(review):
    lines = mix_lines_of(review["id"])
    review["total_units_sold"] = sum(line["units_sold"] for line in lines)
    review["total_gross_sales_cents"] = sum(line["gross_sales_cents"] for line in lines)


@bp.post("/culinary/menu-period-reviews")
def create_review():
    authenticate(("CostAnalyst",))
    body = get_body()
    unit_id = req_id(body, "unit_id")
    period_start = req_instant(body, "period_start")
    period_end = req_instant(body, "period_end")
    basis = req_enum(body, "basis", REVIEW_BASES)
    window(period_start, period_end, "period_start", "period_end")
    unit = find_unit(unit_id)
    row = stamp_new({
        "unit_id": unit["id"],
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
        "status": "OPEN",
        "total_units_sold": 0,
        "total_gross_sales_cents": 0,
        "popularity_threshold_bps": 0,
        "margin_threshold_cents": 0,
        "theoretical_food_cost_cents": 0,
        "actual_food_cost_cents": 0,
        "variance_bps": 0,
        "variance_flag": None,
        "closed_at": None,
    })
    db.period_reviews[row["id"]] = row
    return created(serial.period_review(row))


@bp.get("/culinary/menu-period-reviews/<period_review_id>")
def get_review(period_review_id):
    authenticate(ANY_ROLE)
    return ok(serial.period_review(find_review(period_review_id)))


@bp.get("/culinary/menu-period-reviews")
def list_reviews():
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", REVIEW_STATUSES)
    basis = query_enum("basis", REVIEW_BASES)
    unit_id = query_str("unit_id")
    rows = list(db.period_reviews.values())
    if unit_id is not None:
        rows = [r for r in rows if r["unit_id"] == unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    rows.sort(key=order_key)
    rows.sort(key=lambda r: r["period_end"], reverse=True)
    page, limit, offset, total = paginate(rows, limit, offset, serial.period_review)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Sales mix
# ---------------------------------------------------------------------------
@bp.post("/culinary/menu-period-reviews/<period_review_id>/mix-lines")
def create_mix_line(period_review_id):
    authenticate(("CostAnalyst",))
    body = get_body()
    menu_item_id = req_id(body, "menu_item_id")
    units_sold = req_int(body, "units_sold", minimum=0)
    gross_sales_cents = req_int(body, "gross_sales_cents", minimum=0)
    review = find_review(period_review_id)
    item = find_menu_item(menu_item_id)
    # 20 -- anything that was on the menu during the period may be loaded.
    if item["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_MENU_ITEM_INVALID_STATE",
             "Only an ACTIVE or SUSPENDED menu item can be loaded into a review.")
    # 23 -- the review must still be accepting the mix.
    if review["status"] not in LOADABLE_STATUSES:
        fail("ERR_REVIEW_INVALID_STATE",
             "A %s review no longer accepts mix lines." % review["status"])
    row = stamp_new({
        "period_review_id": review["id"],
        "menu_item_id": item["id"],
        "units_sold": units_sold,
        "gross_sales_cents": gross_sales_cents,
        "plate_cost_cents_snapshot": item["plate_cost_cents"],
        "mix_pct_bps": 0,
        "cm_per_unit_cents": 0,
        "margin_class": "UNCLASSIFIED",
    })
    db.mix_lines[row["id"]] = row
    _recompute_totals(review)
    if review["status"] == "OPEN":
        review["status"] = "MIX_LOADED"
    touch(review)
    return created(serial.mix_line(row))


@bp.get("/culinary/menu-period-reviews/<period_review_id>/mix-lines")
def list_mix_lines(period_review_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    find_review(period_review_id)
    rows = mix_lines_of(period_review_id)
    page, limit, offset, total = paginate(rows, limit, offset, serial.mix_line)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Physical counts
# ---------------------------------------------------------------------------
@bp.post("/culinary/menu-period-reviews/<period_review_id>/count-lines")
def create_count_line(period_review_id):
    user_id, role = authenticate(("UnitManager", "CostAnalyst"))
    body = get_body()
    ingredient_id = req_id(body, "ingredient_id")
    opening = req_int(body, "opening_base_units", minimum=0)
    received = req_int(body, "received_base_units", minimum=0)
    counted = req_int(body, "counted_base_units", minimum=0)
    review = find_review(period_review_id)
    ingredient = find_ingredient(ingredient_id)
    # 14 -- a UnitManager writes only to their own store's review.
    if role == "UnitManager" and review["unit_id"] != user_id:
        fail("ERR_UNIT_SCOPE_VIOLATION",
             "A UnitManager may only record counts for their own store's review.")
    # 23 -- the review must still be accepting counts.
    if review["status"] not in LOADABLE_STATUSES:
        fail("ERR_REVIEW_INVALID_STATE",
             "A %s review no longer accepts count lines." % review["status"])

    used = max(0, opening + received - counted)
    expected = expected_base_units(review["id"], ingredient["id"])
    consuming = consuming_recipe_ids(review["id"], ingredient["id"])
    synced_spec_version = 0
    for recipe_id in consuming:
        recipe = db.recipes.get(recipe_id)
        if recipe is not None:
            synced_spec_version = recipe["version"]
            break
    row = stamp_new({
        "period_review_id": review["id"],
        "ingredient_id": ingredient["id"],
        "opening_base_units": opening,
        "received_base_units": received,
        "counted_base_units": counted,
        "used_base_units": used,
        "expected_base_units": expected,
        "variance_base_units": used - expected,
        "valued_usage_micros": 0,
        "sync_state": "CURRENT",
        "synced_spec_version": synced_spec_version,
    })
    db.count_lines[row["id"]] = row
    touch(review)
    return created(serial.count_line(row))


@bp.get("/culinary/menu-period-reviews/<period_review_id>/count-lines")
def list_count_lines(period_review_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    sync_state = query_enum("sync_state", ("CURRENT", "OUT_OF_DATE"))
    find_review(period_review_id)
    rows = count_lines_of(period_review_id)
    if sync_state is not None:
        rows = [c for c in rows if c["sync_state"] == sync_state]
    page, limit, offset, total = paginate(rows, limit, offset, serial.count_line)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Classification and close
# ---------------------------------------------------------------------------
@bp.post("/culinary/menu-period-reviews/<period_review_id>/classify")
def classify_review(period_review_id):
    authenticate(("CostAnalyst",))
    review = find_review(period_review_id)
    # 23 -- OPEN is admitted so the empty-mix error is what the caller sees.
    if review["status"] not in LOADABLE_STATUSES:
        fail("ERR_REVIEW_INVALID_STATE",
             "A %s review cannot be classified." % review["status"])
    # 40 -- there must be something to classify.
    if not mix_lines_of(review["id"]):
        fail("ERR_EMPTY_MIX", "The review has no mix lines.")
    classify(review)
    return ok(serial.period_review(review))


@bp.post("/culinary/menu-period-reviews/<period_review_id>/close")
def close(period_review_id):
    authenticate(("CostAnalyst",))
    review = find_review(period_review_id)
    # 23 -- only a classified review closes.
    if review["status"] != "CLASSIFIED":
        fail("ERR_REVIEW_INVALID_STATE",
             "Only a CLASSIFIED review can be closed.")
    lines = count_lines_of(review["id"])
    # 25 -- every count line must rest on the current specification.
    for line in lines:
        if line["sync_state"] != "CURRENT":
            fail("ERR_COUNT_SHEET_OUT_OF_DATE",
                 "Count line %s was computed against a specification that has "
                 "since changed." % line["id"])
    # 41 -- and there must be at least one of them.
    if not lines:
        fail("ERR_EMPTY_COUNT_SHEET", "The review has no count sheet lines.")
    close_review(review)
    return ok(serial.period_review(review))

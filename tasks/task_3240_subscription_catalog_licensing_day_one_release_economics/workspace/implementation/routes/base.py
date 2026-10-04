"""Publisher, Title, Region, SubscriptionTier."""
from flask import Blueprint, request

from clock import tried_instant
from checks import page, query_paging
from db import db
from errors import fail
from request_ctx import (ctx, run, want_bool, want_int, want_num, want_str,
                         want_instant, want_platform_set, want_tier_list,
                         want_windows, expect_query)
from response import ok_array, ok_object
from services import calc

bp = Blueprint("base", __name__)

TIER_CODES = ("ESSENTIAL", "PREMIUM", "ULTIMATE")
TIER_FLOORS = ("ESSENTIAL", "PREMIUM", "ULTIMATE")


# --------------------------------------------------------------------------
# Publisher
# --------------------------------------------------------------------------
@bp.route("/catalog/publishers", methods=["POST"])
def create_publisher():
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_publisher, on_eligibility=_unique_publisher)
    row = db.new_row()
    row.update({
        "name": c.get("name"),
        "home_region_code": c.get("home_region_code"),
        "status": "ACTIVE",
        "deal_count": 0,
        "lifetime_licensing_cost_cents": 0,
    })
    db.publishers[row["id"]] = row
    return ok_object(db.public(row), 201)


def _shape_publisher(c):
    want_str(c, "name", required=True)
    want_str(c, "home_region_code", required=True)


def _unique_publisher(c):
    name = c.get("name")
    for row in db.publishers.values():
        if row["name"] == name:
            fail("ERR_INVALID_REQUEST", "Publisher name %s is already registered." % name)


@bp.route("/catalog/publishers/<publisher_id>", methods=["GET"])
def read_publisher(publisher_id):
    c = ctx(["CatalogAdmin", "CatalogAnalyst", "Subscriber"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"publisher": _publisher(publisher_id)}))
    return ok_object(db.public(c.extra["publisher"]))


def _publisher(publisher_id):
    from errors import fail as _fail
    row = db.publishers.get(publisher_id)
    if row is None:
        _fail("ERR_PUBLISHER_NOT_FOUND", "No publisher exists with id %s." % publisher_id)
    return row


def _nothing(_c):
    return None


# --------------------------------------------------------------------------
# Title
# --------------------------------------------------------------------------
@bp.route("/catalog/titles", methods=["POST"])
def create_title():
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_title, on_resolve=_resolve_title_refs, on_eligibility=_unique_title)
    publisher = c.extra["publisher"]
    title = db.new_row()
    title.update({
        "publisher_id": publisher["id"],
        "name": c.get("name"),
        "platform_set": c.get("platform_set"),
        "day_one_eligible": bool(c.get("day_one_eligible", False)),
        "list_price_cents": c.get("list_price_cents"),
        "unit_sales_30d": c.int_of("unit_sales_30d", 0),
        "weighted_engagement_score": 0.0,
        "status": "DRAFT",
    })
    db.titles[title["id"]] = title
    return ok_object(db.public(title), 201)


def _shape_title(c):
    want_str(c, "publisher_id", required=True)
    want_str(c, "name", required=True)
    want_platform_set(c, "platform_set", required=True)
    want_bool(c, "day_one_eligible")
    want_num(c, "list_price_cents", lo=0, required=True)
    want_int(c, "unit_sales_30d", lo=0)


def _resolve_title_refs(c):
    c.extra["publisher"] = _publisher(c.get("publisher_id"))


def _unique_title(c):
    publisher = c.extra["publisher"]
    name = c.get("name")
    for row in db.titles.values():
        if row["publisher_id"] == publisher["id"] and row["name"] == name:
            fail("ERR_INVALID_REQUEST",
                 "Title %s is already registered for this publisher." % name)


@bp.route("/catalog/titles/<title_id>", methods=["GET"])
def read_title(title_id):
    c = ctx(["CatalogAdmin", "CatalogAnalyst", "Subscriber"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"title": _title(title_id)}))
    return ok_object(db.public(c.extra["title"]))


def _title(title_id):
    from errors import fail as _fail
    row = db.titles.get(title_id)
    if row is None:
        _fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % title_id)
    return row


@bp.route("/catalog/titles", methods=["GET"])
def list_titles():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("publisher_id", "status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.titles)
    publisher_id = request.args.get("publisher_id")
    status = request.args.get("status")
    if publisher_id is not None:
        rows = [r for r in rows if r["publisher_id"] == publisher_id]
    if status is not None:
        if status not in ("DRAFT", "RELEASED", "RETIRED"):
            fail("ERR_INVALID_REQUEST", "status must be one of DRAFT, RELEASED, RETIRED.")
        rows = [r for r in rows if r["status"] == status]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Region
# --------------------------------------------------------------------------
@bp.route("/catalog/regions", methods=["POST"])
def create_region():
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_region, on_temporal=_window_overlap, on_eligibility=_unique_region)
    row = db.new_row(full=False)
    row.update({
        "region_code": c.get("region_code"),
        "currency_code": c.get("currency_code"),
        "price_multiplier": c.get("price_multiplier"),
        "availability_ceiling_titles": c.get("availability_ceiling_titles"),
        "catalog_tier_floor": c.get("catalog_tier_floor"),
        "capacity_required_slots": 0.0,
        "capacity_usable_slots": 0.0,
        "capacity_deficit_slots": 0.0,
        "capacity_utilization_pct": 0.0,
        "capacity_status": "WITHIN_CAPACITY",
    })
    db.regions[row["region_code"]] = row
    for window in c.get("maintenance_windows") or []:
        mrow = db.new_row()
        mrow.update({
            # PRD 2.7: the window "names the `region_code` it applies to" — the
            # enclosing region create supplies it for every row it instantiates.
            "region_code": row["region_code"],
            "maintenance_start": window["maintenance_start"],
            "maintenance_end": window["maintenance_end"],
            "capacity_reduction_pct": window["capacity_reduction_pct"],
            "status": "SCHEDULED",
        })
        db.maintenances[mrow["id"]] = mrow
    calc.refresh_capacity(row, db.clock)
    return ok_object(_region_view(row), 201)


def _shape_region(c):
    want_str(c, "region_code", required=True)
    want_str(c, "currency_code", required=True)
    want_num(c, "price_multiplier", lo=0.5, required=True)
    want_int(c, "availability_ceiling_titles", lo=1, required=True)
    want_str(c, "catalog_tier_floor", allowed=TIER_FLOORS, required=True)
    want_windows(c, "maintenance_windows")


def _window_overlap(c):
    windows = c.get("maintenance_windows") or []
    # Every submitted window belongs to the region being created, so an
    # overlap check is purely intra-region (PRD 2.7 / 3.1).
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            a, b = windows[i], windows[j]
            if a["allow_overlap"] or b["allow_overlap"]:
                continue
            if a["maintenance_start"] < b["maintenance_end"] and b["maintenance_start"] < a["maintenance_end"]:
                fail("ERR_MAINTENANCE_WINDOW_OVERLAP",
                     "Two maintenance windows of the region overlap.")
    for window in windows:
        if window["maintenance_end"] <= window["maintenance_start"]:
            fail("ERR_MAINTENANCE_WINDOW_OVERLAP",
                 "A maintenance window must end after it starts.")


def _unique_region(c):
    code = c.get("region_code")
    if code in db.regions:
        fail("ERR_INVALID_REQUEST", "Region %s is already registered." % code)


@bp.route("/catalog/regions/<region_code>", methods=["GET"])
def read_region(region_code):
    c = ctx(["CatalogAdmin", "CatalogAnalyst", "Subscriber"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"region": _region(region_code)}))
    row = c.extra["region"]
    calc.refresh_capacity(row, db.clock)
    return ok_object(_region_view(row))


def _region(region_code):
    from errors import fail as _fail
    row = db.regions.get(region_code)
    if row is None:
        _fail("ERR_REGION_NOT_FOUND", "No region exists with code %s." % region_code)
    return row


def _region_view(row):
    view = db.public(row)
    view.pop("_seq", None)
    return view


# --------------------------------------------------------------------------
# SubscriptionTier
# --------------------------------------------------------------------------
@bp.route("/catalog/tiers", methods=["POST"])
def create_tier():
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_tier, on_fiscal=_tier_caps)
    row = db.new_row()
    row.update({
        "tier_code": c.get("tier_code"),
        "monthly_price_cents": c.get("monthly_price_cents"),
        "console_access": c.get("console_access"),
        "pc_access": c.get("pc_access"),
        "cloud_access": c.get("cloud_access"),
        "online_play_bundle": c.get("online_play_bundle"),
        "member_discount_pct": c.get("member_discount_pct"),
        "discount_retention_days": c.int_of("discount_retention_days", 0),
        "annual_prepay_credit_ratio": c.get("annual_prepay_credit_ratio"),
        "current_subscriber_count": 0,
    })
    db.tiers[row["tier_code"]] = row
    return ok_object(db.public(row), 201)


def _shape_tier(c):
    want_str(c, "tier_code", allowed=TIER_CODES, required=True)
    want_num(c, "monthly_price_cents", lo=0, required=True)
    want_bool(c, "console_access", required=True)
    want_bool(c, "pc_access", required=True)
    want_bool(c, "cloud_access", required=True)
    want_bool(c, "online_play_bundle", required=True)
    want_num(c, "member_discount_pct", lo=0, hi=0.4, required=True)
    want_int(c, "discount_retention_days", lo=0, required=True)
    want_num(c, "annual_prepay_credit_ratio", lo=0, required=True)


def _tier_caps(c):
    code = c.get("tier_code")
    if code in db.tiers:
        fail("ERR_INVALID_REQUEST", "Tier %s already exists." % code)


@bp.route("/catalog/tiers/<tier_code>", methods=["GET"])
def read_tier(tier_code):
    c = ctx(["CatalogAdmin", "CatalogAnalyst", "Subscriber"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"tier": _tier(tier_code)}))
    return ok_object(db.public(c.extra["tier"]))


def _tier(tier_code):
    from errors import fail as _fail
    row = db.tiers.get(tier_code)
    if row is None:
        _fail("ERR_TIER_NOT_FOUND", "No subscription tier exists with code %s." % tier_code)
    return row


@bp.route("/catalog/tiers/<tier_code>/analytics", methods=["GET"])
def tier_analytics(tier_code):
    c = ctx(["CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"tier": _tier(tier_code)}))
    return ok_object(calc.tier_analytics(c.extra["tier"], db.clock))

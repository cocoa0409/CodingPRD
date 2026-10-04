"""StoreDay endpoints: open, list, get, guest counts, close, readings."""

from datetime import datetime

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
import services
from errors import ApiError

bp = Blueprint("store_days", __name__)

ALL_INTERNAL = ["PlatformAdmin", "AssortmentPlanner", "BoutiqueManager", "RetailLead"]
READ_ROLES = ["PlatformAdmin", "BoutiqueManager", "RetailLead"]


def _normalize_date(value):
    """Business date is an ISO 8601 instant at 00:00:00Z."""
    dt = db.parse_ts(value, "business_date")
    return db.fmt_ts(dt.replace(hour=0, minute=0, second=0, microsecond=0))


@bp.post("/retail-ops/store-days")
def create_store_day():
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    data = mw.body()

    location_id = mw.required(data, "location_id")
    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    business_date = _normalize_date(mw.required(data, "business_date"))

    for rec in db.store_days.values():
        if rec.get("location_id") == location_rec["id"] and rec.get("business_date") == business_date:
            raise ApiError("ERR_STORE_DAY_DUPLICATE")

    rec = db.new_record({
        "location_id": location_rec["id"],
        "business_date": business_date,
        "traffic_state": "QUIET",
        "conversion_gate": "OPEN",
        "day_status": "OPEN",
        "restaurant_guest_count": 0,
        "restaurant_sales_cents": 0,
        "waiting_area_shopper_count": 0,
        "waiting_area_converted_count": 0,
        "retail_transaction_count": 0,
        "retail_sales_cents": 0,
        "retail_sales_per_guest_cents": 0,
        "provisional_retail_sales_per_guest_cents": 0,
        "waiting_area_conversion_index_bps": 0,
        "closed_at": None,
    })
    db.store_days[rec["id"]] = rec
    return resp.ok(ser.store_day(rec), 201)


@bp.get("/retail-ops/store-days")
def list_store_days():
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    date_from = mw.query_str("business_date_from")
    date_to = mw.query_str("business_date_to")
    records = []
    for rec in db.store_days.values():
        if not mw.matches(rec, {
            "location_id": mw.query_str("location_id"),
            "day_status": mw.query_str("day_status"),
            "conversion_gate": mw.query_str("conversion_gate"),
        }):
            continue
        if date_from and rec.get("business_date", "") < date_from:
            continue
        if date_to and rec.get("business_date", "") > date_to:
            continue
        records.append(rec)
    records = resp.order_records(records)
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.store_day(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/store-days/<day_id>")
def get_store_day(day_id):
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    rec = db.get_or_404(db.store_days, day_id, "ERR_STORE_DAY_NOT_FOUND")
    return resp.ok(ser.store_day(rec))


@bp.get("/retail-ops/store-days/<day_id>/capacity-readings")
def list_store_day_readings(day_id):
    ctx = mw.context()
    mw.require_role(ctx, READ_ROLES)
    db.get_or_404(db.store_days, day_id, "ERR_STORE_DAY_NOT_FOUND")
    records = resp.order_records(
        [r for r in db.capacity_readings.values() if r.get("store_day_id") == day_id])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.capacity_reading(r) for r in page], pagination=pagination)


# ---------------------------------------------------------------------------
# Guest counts
# ---------------------------------------------------------------------------

def _derive_posture(day, guest_count):
    """Re-derive the (traffic_state, conversion_gate) pair (PRD 3.1).

    The gate is *follows the day's disputes* at every count, not only below 40:
    a quiet day is SUSPENDED while at least one of its receipts is DISPUTED and
    OPEN otherwise, and every count landing at 40 or above returns the gate to
    OPEN because there is no other rule that holds it elsewhere (PRD 3.1: "with
    no disputed receipt outstanding its gate returns to OPEN in the same
    movement").
    """
    disputed = any(r.get("store_day_id") == day["id"] and r.get("status") == "DISPUTED"
                   for r in db.receipts.values())
    open_gate = "SUSPENDED" if disputed else "OPEN"
    if guest_count >= 120:
        day["traffic_state"] = "RUSH"
        day["conversion_gate"] = "GATED_RESTRICTED"
    elif guest_count >= 40:
        day["traffic_state"] = "STEADY"
        day["conversion_gate"] = open_gate
    else:
        day["traffic_state"] = "QUIET"
        day["conversion_gate"] = open_gate


@bp.post("/retail-ops/store-days/<day_id>/guest-counts")
def post_guest_counts(day_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager", "RetailLead"])

    # Priority 3 — existence of the typed path segment.
    day = db.get_or_404(db.store_days, day_id, "ERR_STORE_DAY_NOT_FOUND")
    data = mw.body()

    # Priority 7 — state. A closed day is terminal (PRD 2.10, 3.1).
    if day.get("day_status") != "OPEN":
        raise ApiError("ERR_STORE_DAY_CLOSED")

    guest_count = mw.required(data, "restaurant_guest_count", int)
    restaurant_sales = mw.required(data, "restaurant_sales_cents", int)
    shoppers = mw.required(data, "waiting_area_shopper_count", int)
    converted = mw.required(data, "waiting_area_converted_count", int)
    for field, value in (("restaurant_guest_count", guest_count),
                         ("restaurant_sales_cents", restaurant_sales),
                         ("waiting_area_shopper_count", shoppers),
                         ("waiting_area_converted_count", converted)):
        if value < 0:
            raise ApiError("ERR_INVALID_REQUEST", "%s must not be negative." % field)

    # PRD 2.6 — the expected version is non-optional on this endpoint.
    expected = mw.required(data, "expected_store_day_version", int)
    if expected != day.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    day["restaurant_guest_count"] = guest_count
    day["restaurant_sales_cents"] = restaurant_sales
    day["waiting_area_shopper_count"] = shoppers
    day["waiting_area_converted_count"] = converted

    _derive_posture(day, guest_count)
    calc.recompute_store_day_retail_metrics(day)
    calc.recompute_conversion_index(day)
    db.touch(day)
    return resp.ok(ser.store_day(day))


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/store-days/<day_id>/close")
def close_store_day(day_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])

    day = db.get_or_404(db.store_days, day_id, "ERR_STORE_DAY_NOT_FOUND")
    data = mw.body()

    if day.get("day_status") != "OPEN":
        raise ApiError("ERR_INVALID_STATE")

    location_rec = db.locations.get(day.get("location_id"))
    brand_rec = calc.brand_of_location(location_rec)

    # Priority 5 — the fiscal period must still be open for recognition.
    if brand_rec is not None and brand_rec.get("fiscal_period_status") != "OPEN":
        raise ApiError("ERR_FISCAL_PERIOD_CLOSED")

    # Priority 7 — every receipt of this day must be past DRAFT.
    for rec in db.receipts.values():
        if rec.get("store_day_id") == day["id"] and rec.get("status") == "DRAFT":
            raise ApiError("ERR_INVALID_STATE")

    # PRD 2.6 — the close accepts expected_store_day_version but the API
    # declares no stale-version rejection for it, so a mismatch is recorded
    # and the close proceeds.
    expected = mw.optional(data, "expected_store_day_version", None, int)
    if expected is not None:
        day["_last_expected_version"] = expected

    services.close_store_day(day)
    return resp.ok(ser.store_day(day))


# ---------------------------------------------------------------------------
# Manual backroom capacity readings
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/locations/<location_id>/capacity-readings")
def create_capacity_reading(location_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])

    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    data = mw.body()

    store_day_id = mw.required(data, "store_day_id")
    db.get_or_404(db.store_days, store_day_id, "ERR_STORE_DAY_NOT_FOUND")

    measured_at = db.fmt_ts(db.parse_ts(mw.required(data, "measured_at"), "measured_at"))
    backroom_units = mw.optional(data, "backroom_units", 0, int)
    food_storage_units = mw.optional(data, "food_storage_units", 0, int)
    dated_units = mw.optional(data, "dated_units", 0, int)
    for field, value in (("backroom_units", backroom_units),
                         ("food_storage_units", food_storage_units),
                         ("dated_units", dated_units)):
        if value < 0:
            raise ApiError("ERR_INVALID_REQUEST", "%s must not be negative." % field)

    source = mw.required(data, "source")
    if source not in {"RECEIVING", "SALES_FLOOR_MOVE", "CYCLE_COUNT"}:
        raise ApiError("ERR_INVALID_REQUEST", "source is not a declared reading source.")

    reading = services.build_capacity_reading(
        location_rec, store_day_id, None, measured_at,
        backroom_units, food_storage_units, dated_units, source)
    return resp.ok(ser.capacity_reading(reading), 201)


@bp.get("/retail-ops/locations/<location_id>/capacity-readings")
def list_location_readings(location_id):
    ctx = mw.context()
    mw.require_role(ctx, READ_ROLES)
    db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    records = resp.order_records([r for r in db.capacity_readings.values() if mw.matches(r, {
        "location_id": location_id,
        "store_day_id": mw.query_str("store_day_id"),
        "trigger_transfer_id": mw.query_str("trigger_transfer_id"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.capacity_reading(r) for r in page], pagination=pagination)
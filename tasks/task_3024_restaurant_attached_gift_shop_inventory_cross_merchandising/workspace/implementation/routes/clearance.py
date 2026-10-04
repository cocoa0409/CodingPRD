"""ClearanceSchedule endpoints: create, activate, extend, reactivate,
liquidate, cancel."""

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
import services
from errors import ApiError

bp = Blueprint("clearance", __name__)

CLEARANCE_READ_ROLES = ["PlatformAdmin", "AssortmentPlanner", "BoutiqueManager", "RetailLead"]


def _statuses(status_value):
    return {status_value}


@bp.post("/retail-ops/clearance-schedules")
def create_schedule():
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager", "AssortmentPlanner"])
    data = mw.body()

    location_id = mw.required(data, "location_id")
    db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")

    # Priority 9 — the item reference.
    item_id = mw.required(data, "item_id")
    db.get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")

    start = db.parse_ts(mw.required(data, "start_date"), "start_date")
    end = db.parse_ts(mw.required(data, "end_date"), "end_date")
    if end < start:
        raise ApiError("ERR_INVALID_REQUEST", "end_date must be at or after start_date.")

    # Priority 13 — the buffer rule.
    services.window_collides(location_id, item_id, start, end)

    rec = db.new_record({
        "location_id": location_id,
        "item_id": item_id,
        "start_date": db.fmt_ts(start),
        "end_date": db.fmt_ts(end),
        "stage": "S1",
        "markdown_pct": 0.0,
        "liquidation_price_cents": 0,
        "status": "DRAFT",
        "remaining_units": 0,
        "liquidated_units": 0,
        "liquidation_bucket_units": [],
        "liquidation_blended_cents": 0,
        "extension_count": 0,
        "reactivation_count": 0,
        "activated_at": None,
    })
    db.clearance_schedules[rec["id"]] = rec
    return resp.ok(ser.clearance_schedule(rec), 201)


@bp.get("/retail-ops/clearance-schedules")
def list_schedules():
    ctx = mw.context()
    mw.require_role(ctx, CLEARANCE_READ_ROLES)
    records = resp.order_records([r for r in db.clearance_schedules.values() if mw.matches(r, {
        "location_id": mw.query_str("location_id"),
        "item_id": mw.query_str("item_id"),
        "status": mw.query_str("status"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.clearance_schedule(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/clearance-schedules/<schedule_id>")
def get_schedule(schedule_id):
    ctx = mw.context()
    mw.require_role(ctx, CLEARANCE_READ_ROLES)
    rec = db.get_or_404(db.clearance_schedules, schedule_id, "ERR_CLEARANCE_NOT_FOUND")
    return resp.ok(ser.clearance_schedule(rec))


@bp.post("/retail-ops/clearance-schedules/<schedule_id>/activate")
def activate_schedule(schedule_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.clearance_schedules, schedule_id, "ERR_CLEARANCE_NOT_FOUND")

    location_rec = db.locations.get(rec.get("location_id"))
    item_rec = db.items.get(rec.get("item_id"))

    # Priority 7 — state.
    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    # Priority 14 — the active-clearance slot limit.  It is declared as a
    # front-of-ladder rule ("A location already at its limit refuses the
    # activation with ERR_CLEARANCE_SLOT_LIMIT at priority 14"), ahead of the
    # window-placement condition, so a location at its cap reports the slot
    # limit rather than a state error.
    calc.recompute_active_clearance_count(location_rec)
    if location_rec.get("active_clearance_count", 0) >= location_rec.get("clearance_max_active", 3):
        raise ApiError("ERR_CLEARANCE_SLOT_LIMIT")

    # The clock must fall inside [start_date, end_date) (PRD 3.8).
    start = db.parse_ts(rec.get("start_date"), "start_date")
    end = db.parse_ts(rec.get("end_date"), "end_date")
    if not (start <= db.now() < end):
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "ACTIVE"
    rec["activated_at"] = db.fmt_ts(db.now())
    services.set_stage(rec, "S1")
    rec["remaining_units"] = item_rec.get("on_hand_units", 0) or 0
    item_rec["current_markdown_pct"] = rec["markdown_pct"]
    item_rec["status"] = "CLEARANCE"
    item_rec["clearance_week"] = 0
    calc.apply_stacked_markdown(item_rec)
    db.touch(item_rec)

    calc.recompute_active_clearance_count(location_rec)
    db.touch(rec)
    return resp.ok(ser.clearance_schedule(rec))


@bp.post("/retail-ops/clearance-schedules/<schedule_id>/extend")
def extend_schedule(schedule_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.clearance_schedules, schedule_id, "ERR_CLEARANCE_NOT_FOUND")
    data = mw.body()

    if rec.get("status") not in {"ACTIVE", "EXTENDED"}:
        raise ApiError("ERR_INVALID_STATE")

    extra_days = mw.required(data, "extra_days", int)
    if extra_days < 0:
        raise ApiError("ERR_INVALID_REQUEST", "extra_days must not be negative.")

    services.extend_schedule(rec, extra_days)
    return resp.ok(ser.clearance_schedule(rec))


@bp.post("/retail-ops/clearance-schedules/<schedule_id>/reactivate")
def reactivate_schedule(schedule_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.clearance_schedules, schedule_id, "ERR_CLEARANCE_NOT_FOUND")

    # Priority 7 — state.
    if rec.get("status") != "EXTENDED":
        raise ApiError("ERR_INVALID_STATE")

    # Priority 13 — the buffer rule guards the reactivated window.
    previous_end = db.parse_ts(rec.get("end_date"), "end_date")

    # Priority 25 — the reactivation-count limit.
    if rec.get("reactivation_count", 0) >= 2:
        raise ApiError("ERR_CLEARANCE_WINDOW_REACTIVATION_LIMIT")

    brand_rec = calc.brand_of_location(db.locations.get(rec.get("location_id")))
    buffer_hours = brand_rec.get("clearance_buffer_hours", 24) if brand_rec else 24

    new_start = db.plus_hours(previous_end, buffer_hours)
    new_end = db.plus_days(new_start, 7)
    services.window_collides(rec.get("location_id"), rec.get("item_id"), new_start, new_end,
                             exclude_id=rec["id"])

    rec["status"] = "ACTIVE"
    rec["reactivation_count"] = rec.get("reactivation_count", 0) + 1
    rec["start_date"] = db.fmt_ts(new_start)
    rec["end_date"] = db.fmt_ts(new_end)
    rec["activated_at"] = db.fmt_ts(db.now())
    db.touch(rec)

    item_rec = db.items.get(rec.get("item_id"))
    if item_rec is not None:
        item_rec["clearance_week"] = 0
        calc.apply_stacked_markdown(item_rec)
        db.touch(item_rec)
    return resp.ok(ser.clearance_schedule(rec))


@bp.post("/retail-ops/clearance-schedules/<schedule_id>/cancel")
def cancel_schedule(schedule_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.clearance_schedules, schedule_id, "ERR_CLEARANCE_NOT_FOUND")

    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "CANCELLED"
    db.touch(rec)
    return resp.ok(ser.clearance_schedule(rec))


@bp.post("/retail-ops/clearance-schedules/<schedule_id>/liquidate")
def liquidate_schedule(schedule_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.clearance_schedules, schedule_id, "ERR_CLEARANCE_NOT_FOUND")

    status = rec.get("status")
    if status not in {"ACTIVE", "EXTENDED"}:
        raise ApiError("ERR_INVALID_STATE")

    if status == "ACTIVE":
        # Priority 15 — stage S4 and item status CLEARANCE are both required.
        item_rec = db.items.get(rec.get("item_id"))
        if rec.get("stage") != "S4" or item_rec is None or item_rec.get("status") != "CLEARANCE":
            raise ApiError("ERR_CLEARANCE_NOT_FINAL")
    else:
        if rec.get("stage") != "S4":
            raise ApiError("ERR_CLEARANCE_NOT_FINAL")

    item_rec = db.get_or_404(db.items, rec.get("item_id"), "ERR_ITEM_NOT_FOUND")
    location_rec = db.locations.get(rec.get("location_id"))

    # The waterfall is computed before the snapshot is zeroed.
    price, blended, bucket_units = calc.liquidation_tier_price(rec, item_rec)
    rec["liquidation_price_cents"] = price
    rec["liquidation_blended_cents"] = blended
    rec["liquidation_bucket_units"] = bucket_units

    liquidated = rec.get("remaining_units", 0) or 0
    rec["liquidated_units"] = liquidated
    rec["remaining_units"] = 0
    rec["status"] = "LIQUIDATED"

    item_rec["on_hand_units"] = (item_rec.get("on_hand_units", 0) or 0) - liquidated
    item_rec["status"] = "DISCONTINUED"

    if status == "ACTIVE":
        # PRD 3.8: the ACTIVE branch unwinds the clearance pricing entirely.
        item_rec["current_markdown_pct"] = 0.0
        item_rec["effective_price_cents"] = item_rec.get("unit_retail_cents", 0)
    else:
        calc.apply_stacked_markdown(item_rec)
    db.touch(item_rec)

    calc.recompute_active_clearance_count(location_rec)
    db.touch(rec)
    return resp.ok(ser.clearance_schedule(rec))
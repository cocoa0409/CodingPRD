"""Shared cascade logic used by more than one route module."""

from decimal import Decimal

import calculations as calc
import db
from errors import ApiError


# ---------------------------------------------------------------------------
# Clearance cadence
# ---------------------------------------------------------------------------

def set_stage(schedule, stage):
    schedule["stage"] = stage
    schedule["markdown_pct"] = db.pct4(calc.STAGE_MARKDOWN_PCT[stage])


def advance_one_stage(schedule):
    """Walk the cadence forward a single step, capped at S4."""
    index = calc.STAGE_ORDER.index(schedule.get("stage", "S1"))
    if index >= len(calc.STAGE_ORDER) - 1:
        set_stage(schedule, "S4")
        return False
    set_stage(schedule, calc.STAGE_ORDER[index + 1])
    return True


def mirror_item_markdown(item_rec, schedule):
    item_rec["current_markdown_pct"] = schedule.get("markdown_pct", 0)


def refresh_item_prices(item_rec):
    item_rec["clearance_week"] = calc.item_clearance_week(item_rec)
    calc.apply_stacked_markdown(item_rec)
    db.touch(item_rec)
    return item_rec


def advance_schedule_markdown(schedule, steps=1, mirror=True):
    """Advance a schedule's stage by `steps`, capped at S4 (PRD 3.8)."""
    item_rec = db.items.get(schedule.get("item_id"))
    for _ in range(max(1, steps)):
        advance_one_stage(schedule)
    if mirror:
        mirror_item_markdown(item_rec, schedule)
    db.touch(schedule)
    if mirror:
        refresh_item_prices(item_rec)
    else:
        item_rec["clearance_week"] = calc.item_clearance_week(item_rec)
        calc.apply_stacked_markdown(item_rec)
        db.touch(item_rec)
    return schedule


def weeks_on_clearance(schedule):
    activated = schedule.get("activated_at")
    if not activated:
        return 0
    delta = db.now() - db.parse_ts(activated, "activated_at")
    return max(0, int(delta.total_seconds() // (7 * 24 * 3600)))


def clearance_schedules_for_location(location_id, statuses=None):
    return [s for s in db.clearance_schedules.values()
            if s.get("location_id") == location_id
            and (statuses is None or s.get("status") in statuses)]


def window_collides(location_id, item_id, start, end, exclude_id=None):
    """PRD 3.8 / priority 13: windows on one (location, item) must be buffered.

    The window is half-open [start_date, end_date); two windows must be
    separated by at least Brand.clearance_buffer_hours, and a zero-length gap
    is a rejection.
    """
    location_rec = db.locations.get(location_id)
    brand_rec = calc.brand_of_location(location_rec)
    buffer_hours = brand_rec.get("clearance_buffer_hours", 24) if brand_rec else 24

    for other in db.clearance_schedules.values():
        if other["id"] == exclude_id:
            continue
        if other.get("location_id") != location_id or other.get("item_id") != item_id:
            continue
        if other.get("status") == "CANCELLED":
            continue
        cur_start = db.parse_ts(other.get("start_date"), "start_date")
        cur_end = db.parse_ts(other.get("end_date"), "end_date")
        if _buffered_overlap(cur_start, cur_end, start, end, buffer_hours):
            raise ApiError("ERR_CLEARANCE_WINDOW_OVERLAP")
    return True


def _buffered_overlap(a_start, a_end, b_start, b_end, buffer_days):
    """Half-open windows [start, end) separated by at least the buffer.

    A gap of zero is a rejection, not an acceptance (PRD 3.8).
    """
    from datetime import timedelta
    buf = timedelta(hours=float(buffer_days))

    # Windows must not intersect at all.
    if b_start < a_end and a_start < b_end:
        return True
    # Forward gap smaller than the buffer.
    if b_start >= a_end and (b_start - a_end) < buf:
        return True
    # Backward gap smaller than the buffer.
    if a_start >= b_end and (a_start - b_end) < buf:
        return True
    return False


def extend_schedule(schedule, days):
    schedule["status"] = "EXTENDED"
    schedule["extension_count"] = schedule.get("extension_count", 0) + 1
    schedule["end_date"] = db.fmt_ts(db.plus_days(
        db.parse_ts(schedule.get("end_date"), "end_date"), days))
    db.touch(schedule)
    return schedule


# ---------------------------------------------------------------------------
# Backroom capacity
# ---------------------------------------------------------------------------

def build_capacity_reading(location_rec, store_day_id, trigger_transfer_id,
                           measured_at, backroom_units, food_storage_units,
                           dated_units, source):
    brand_rec = calc.brand_of_location(location_rec)
    corridor = brand_rec.get("food_storage_corridor_units", 40) if brand_rec else 40

    occupancy = (backroom_units or 0) + (food_storage_units or 0) + (dated_units or 0)
    committed = location_rec.get("backroom_committed_units", 0) or 0
    free = (location_rec.get("backroom_capacity_units", 0) or 0) - occupancy - committed

    reading = db.new_record({
        "location_id": location_rec["id"],
        "store_day_id": store_day_id,
        "trigger_transfer_id": trigger_transfer_id,
        "measured_at": measured_at,
        "backroom_units": backroom_units or 0,
        "food_storage_units": food_storage_units or 0,
        "dated_units": dated_units or 0,
        "source": source,
        "occupancy_units": occupancy,
        "committed_units": committed,
        "free_units": free,
        "capacity_breach": free < corridor,
    })
    db.capacity_readings[reading["id"]] = reading

    # A receiving reading is incremental (it reports only the units that just
    # arrived) whereas a manual measurement is absolute, so the location's
    # occupancy is overwritten for manual readings and adjusted for receiving.
    if source == "RECEIVING":
        location_rec["backroom_occupancy_units"] = (
            (location_rec.get("backroom_occupancy_units", 0) or 0) + (backroom_units or 0))
        if food_storage_units:
            location_rec["food_storage_units"] = food_storage_units
        reading["occupancy_units"] = location_rec["backroom_occupancy_units"]
    else:
        location_rec["backroom_occupancy_units"] = backroom_units or 0
        location_rec["food_storage_units"] = food_storage_units or 0

    calc.recompute_location_posture(location_rec)
    db.touch(location_rec)

    if reading["capacity_breach"]:
        sweep_breach_markdowns(location_rec["id"])
    return reading


def sweep_breach_markdowns(location_id):
    """A breached reading advances every ACTIVE or DRAFT schedule one stage."""
    for schedule in list(clearance_schedules_for_location(location_id, {"ACTIVE", "DRAFT"})):
        advance_schedule_markdown(schedule, steps=1, mirror=True)


# ---------------------------------------------------------------------------
# Store-day close
# ---------------------------------------------------------------------------

def close_store_day(day):
    """PRD 3.5's fixed sweep order."""
    location_rec = db.locations.get(day["location_id"])
    brand_rec = calc.brand_of_location(location_rec)

    # 1. Bubble SETTLED receipts of this day to CLOSED.
    for rec in db.receipts.values():
        if rec.get("store_day_id") != day["id"]:
            continue
        if rec.get("status") != "SETTLED":
            continue
        check = db.guest_checks.get(rec.get("guest_check_id")) if rec.get("guest_check_id") else None
        if check is not None and check.get("settlement_status") != "SETTLED":
            continue
        rec["status"] = "CLOSED"
        rec["closed_at"] = db.fmt_ts(db.now())
        if brand_rec is not None:
            calc.post_recognition(rec, brand_rec)
        db.touch(rec)

    # 2. Store-day retail metrics.
    calc.recompute_store_day_retail_metrics(day)

    # 3. Close the day.  The roll-up below is over the brand's CLOSED store
    # days, and the day being closed is one of them.
    day["day_status"] = "CLOSED"
    day["closed_at"] = db.fmt_ts(db.now())

    # 4. Brand revenue ledger and the guest-count-weighted roll-up.
    if brand_rec is not None:
        calc.recompute_brand_revenue(brand_rec)
        calc.recompute_brand_rpg(brand_rec)
        db.touch(brand_rec)

    # 5. Post-holiday clearance extension.
    if brand_rec is not None and day["retail_sales_per_guest_cents"] < brand_rec.get(
            "liquidation_trigger_rpg_cents", 700):
        for schedule in clearance_schedules_for_location(location_rec["id"], {"ACTIVE"}):
            if db.parse_ts(schedule.get("end_date"), "end_date") < db.now():
                extend_schedule(schedule, 14)

    # 6. Stamp the day.
    db.touch(day)
    return day
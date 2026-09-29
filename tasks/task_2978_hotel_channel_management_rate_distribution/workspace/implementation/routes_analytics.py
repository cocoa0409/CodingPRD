"""Channel performance, booking pace, channel mix and the logical clock (PRD 3.11)."""

from flask import Blueprint

import calc
import guards
import refs
import shape
import store
from envelope import ok
from errors import fail
from guards import must

bp = Blueprint("analytics", __name__)

BASES = ("STAY", "BOOKED")
BASELINES = ("ROLLING", "STLY")


@bp.get("/distribution/channels/<cid>/performance")
def channel_performance(cid):
    shape.auth("RevenueManager", "RevenueDirector")
    channel = must("channels", cid, "ERR_CHANNEL_NOT_FOUND")
    start_date = shape.q_date("window_start_date", required=True)
    end_date = shape.q_date("window_end_date", required=True)
    basis = shape.q_enum("basis", BASES, default="STAY")
    prop = refs.prop_of_channel(channel)
    guards.analytics_window(prop, start_date, end_date)
    metrics = calc.window_amounts(channel["id"], start_date, end_date, basis)
    data = {
        "channel_id": channel["id"],
        "basis": basis,
        "window_start_date": start_date,
        "window_end_date": end_date,
        "gross_amount_cents": metrics["gross_amount_cents"],
        "commission_amount_cents": metrics["commission_amount_cents"],
        "net_amount_cents": metrics["net_amount_cents"],
        "room_nights": metrics["room_nights"],
        "net_adr_cents": metrics["net_adr_cents"],
        "commission_cost_ratio_bp": metrics["commission_cost_ratio_bp"],
        "health_score_bp": calc.health_score_bp(channel["id"]),
    }
    return ok(data)


@bp.get("/distribution/room-types/<rid>/pace")
def room_type_pace(rid):
    shape.auth("RevenueManager", "RevenueDirector")
    room_type = must("room_types", rid, "ERR_ROOM_TYPE_NOT_FOUND")
    target_stay_date = shape.q_date("target_stay_date", required=True)
    baseline = shape.q_enum("baseline", BASELINES, default="ROLLING")
    if target_stay_date <= refs.clock_date_str():
        fail("ERR_ANALYTICS_WINDOW_INVALID")
    return ok(calc.booking_pace(room_type, target_stay_date, baseline))


@bp.get("/distribution/properties/<pid>/channel-mix")
def channel_mix(pid):
    shape.auth("RevenueManager", "RevenueDirector")
    prop = must("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    start_date = shape.q_date("window_start_date", required=True)
    end_date = shape.q_date("window_end_date", required=True)
    guards.analytics_window(prop, start_date, end_date)
    ranked = calc.channel_mix(prop, start_date, end_date)
    if not ranked:
        fail("ERR_NO_ELIGIBLE_CHANNEL")
    return ok({
        "property_id": prop["id"],
        "window_start_date": start_date,
        "window_end_date": end_date,
        "ranked_channels": ranked,
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    shape.auth("PlatformAdmin")
    body = shape.body_obj()
    moment = shape.v_instant(body, "current_utc", required=True)
    store.set_clock(moment)
    return ok({"current_utc": store.now_iso()})

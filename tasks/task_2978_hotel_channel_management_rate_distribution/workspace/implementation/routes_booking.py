"""Booking a stay, charging it and cancelling it (PRD 3.9)."""

from flask import Blueprint

import calc
import cascade
import guards
import refs
import serialize
import shape
import store
from envelope import created, ok
from errors import fail
from guards import must, page
from refs import get, put, rows
from routes_mapping import rate_eligibility

bp = Blueprint("booking", __name__)

ALL_ROLES = ("PlatformAdmin", "RevenueManager", "RevenueDirector",
             "ChannelOpsEngineer", "ChannelPartner")
RESERVATION_STATES = ("CONFIRMED", "CANCELLED")


def _allotment_draw(channel_id, room_type_id, nights_list):
    """The OPEN allotment covering every night with an unconsumed unit, if any."""
    for alloc in refs.where("allocations", room_type_id=room_type_id):
        if alloc["channel_id"] != channel_id:
            continue
        if alloc["allocation_state"] != "OPEN":
            continue
        if alloc["allocated_units"] - alloc["consumed_units"] < 1:
            continue
        if all(refs.covers(alloc, night) for night in nights_list):
            return alloc
    return None


@bp.post("/distribution/reservations")
def create_reservation():
    uid, role = shape.auth("RevenueManager", "ChannelPartner")
    raw = shape.peek_body()
    if role == "ChannelPartner" and isinstance(raw.get("channel_id"), str) \
            and raw["channel_id"] != uid:
        fail("ERR_CHANNEL_OWNERSHIP_VIOLATION")
    if raw.get("override_overbooking") is True and role == "ChannelPartner":
        fail("ERR_OVERRIDE_NOT_PERMITTED",
             "Only a RevenueManager or RevenueDirector may override overbooking.")
    body = shape.body_obj()
    channel_id = shape.v_string(body, "channel_id", required=True)
    rate_plan_id = shape.v_string(body, "rate_plan_id", required=True)
    room_type_id = shape.v_string(body, "room_type_id", required=True)
    arrival_date = shape.v_date(body, "arrival_date", required=True)
    nights = shape.v_int(body, "nights", required=True, lo=1, hi=14)
    member_flag = shape.v_bool(body, "member_flag", default=False)
    geo_market_code = shape.v_string(body, "geo_market_code", minlen=2, maxlen=8,
                                     pattern=r"^[A-Z0-9-]+$")
    account_code = shape.v_string(body, "negotiated_account_code", minlen=2, maxlen=16,
                                  pattern=r"^[A-Z0-9-]+$")
    override = shape.v_bool(body, "override_overbooking", default=False)
    channel = get("channels", channel_id)
    if channel is None:
        fail("ERR_CHANNEL_NOT_FOUND")
    plan = get("rate_plans", rate_plan_id)
    if plan is None:
        fail("ERR_RATE_PLAN_NOT_FOUND")
    room_type = get("room_types", room_type_id)
    if room_type is None:
        fail("ERR_ROOM_TYPE_NOT_FOUND")
    if not (channel["property_id"] == plan["property_id"] ==
            room_type["property_id"]):
        fail("ERR_PROPERTY_SCOPE_MISMATCH")
    departure_date = refs.shift(arrival_date, nights)
    nights_list = refs.stay_nights(arrival_date, nights)
    connection = refs.connection_of_channel(channel["id"])
    if connection is not None and \
            connection["connection_state"] not in ("HEALTHY", "DEGRADED"):
        fail("ERR_CONNECTION_NOT_SELLABLE")
    if connection is None:
        fail("ERR_CHANNEL_CONNECTION_MISSING")
    days = {}
    for night in nights_list:
        day = refs.inventory_day(room_type["id"], night)
        if day is None:
            fail("ERR_INVENTORY_DAY_NOT_OPEN")
        days[night] = day
    prop = refs.prop_of_channel(channel)
    guards.require_stay_horizon(prop, arrival_date, departure_date)
    rate_eligibility(plan, channel, nights_list, member_flag, geo_market_code,
                     account_code)
    blocked = calc.restriction_block(room_type["id"], plan["id"], arrival_date, nights)
    if blocked is not None:
        fail(blocked)
    allotment = _allotment_draw(channel["id"], room_type["id"], nights_list)
    overridden = False
    if allotment is None:
        for night in nights_list:
            if days[night]["shared_pool_units"] < 1:
                fail("ERR_OVERBOOKING_CEILING_EXCEEDED")
        in_band = False
        for night in nights_list:
            day = days[night]
            if day["allocated_units"] + day["committed_units"] >= \
                    day["physical_capacity_units"]:
                in_band = True
        if in_band:
            if not override:
                fail("ERR_OVERBOOK_OVERRIDE_REQUIRED")
            overridden = True
    charge = calc.charge_stay(plan, channel, arrival_date, nights, member_flag,
                              geo_market_code)
    rec = store.base_record()
    rec.update({
        "property_id": channel["property_id"],
        "channel_id": channel["id"],
        "rate_plan_id": plan["id"],
        "room_type_id": room_type["id"],
        "arrival_date": arrival_date,
        "nights": nights,
        "departure_date": departure_date,
        "member_flag": member_flag,
        "geo_market_code": geo_market_code,
        "negotiated_account_code": account_code,
        "override_overbooking": override,
        "reservation_state": "CONFIRMED",
        "overbooking_overridden": overridden,
        "cancelled_at": None,
        # Internal only, never serialized: which allotment this stay drew its
        # unit from, or None for a shared-pool draw (PRD 3.8 booking admission).
        "_draw_allocation_id": allotment["id"] if allotment is not None else None,
    })
    rec.update(charge)
    put("reservations", rec)
    channel["gross_revenue_cents"] += rec["gross_amount_cents"]
    channel["commission_accrued_cents"] += rec["commission_amount_cents"]
    channel["net_revenue_cents"] += rec["net_amount_cents"]
    channel["room_nights_sold"] += nights
    channel["bookings_count"] += 1
    store.bump(channel)
    cascade.refresh_room_type(room_type["id"])
    return created(serialize.reservation_out(rec))


@bp.post("/distribution/reservations/<rid>/cancel")
def cancel_reservation(rid):
    uid, role = shape.auth("RevenueManager", "ChannelPartner")
    reservation = must("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    if role == "ChannelPartner" and reservation["channel_id"] != uid:
        fail("ERR_CHANNEL_OWNERSHIP_VIOLATION")
    if reservation["reservation_state"] != "CONFIRMED":
        fail("ERR_RESERVATION_NOT_CANCELLABLE")
    reservation["reservation_state"] = "CANCELLED"
    reservation["cancelled_at"] = store.now_iso()
    store.bump(reservation)
    channel = get("channels", reservation["channel_id"])
    channel["gross_revenue_cents"] -= reservation["gross_amount_cents"]
    channel["commission_accrued_cents"] -= reservation["commission_amount_cents"]
    channel["net_revenue_cents"] -= reservation["net_amount_cents"]
    channel["room_nights_sold"] -= reservation["nights"]
    channel["cancellations_count"] += 1
    store.bump(channel)
    cascade.refresh_room_type(reservation["room_type_id"])
    return ok(serialize.reservation_out(reservation))


@bp.get("/distribution/reservations")
def list_reservations():
    uid, role = shape.auth(*ALL_ROLES)
    property_id = shape.q_id("property_id")
    channel_id = shape.q_id("channel_id")
    rate_plan_id = shape.q_id("rate_plan_id")
    room_type_id = shape.q_id("room_type_id")
    state = shape.q_enum("reservation_state", RESERVATION_STATES)
    records = rows("reservations")
    if role == "ChannelPartner":
        records = [r for r in records if r["channel_id"] == uid]
    if property_id is not None:
        records = [r for r in records if r["property_id"] == property_id]
    if channel_id is not None:
        records = [r for r in records if r["channel_id"] == channel_id]
    if rate_plan_id is not None:
        records = [r for r in records if r["rate_plan_id"] == rate_plan_id]
    if room_type_id is not None:
        records = [r for r in records if r["room_type_id"] == room_type_id]
    if state is not None:
        records = [r for r in records if r["reservation_state"] == state]
    return page(serialize.reservation_out, records)


@bp.get("/distribution/reservations/<rid>")
def read_reservation(rid):
    uid, role = shape.auth(*ALL_ROLES)
    reservation = must("reservations", rid, "ERR_RESERVATION_NOT_FOUND")
    if role == "ChannelPartner" and reservation["channel_id"] != uid:
        fail("ERR_RESERVATION_NOT_FOUND")
    return ok(serialize.reservation_out(reservation))

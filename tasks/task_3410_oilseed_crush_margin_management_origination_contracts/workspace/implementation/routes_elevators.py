"""Elevators: register, read, list, carry assessment."""
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH
from dates import months_between, valid_month
from envelope import success_list, success_obj
from errors import fail
from quotes import asof
from store import db, new_id, stamp_new, to_jsonable
from validate import body_dict, paginate, req_decimal, req_str, sort_created

bp = Blueprint("elevators", __name__)


@bp.post("/api/elevators")
def create_elevator():
    require_roles("PlatformAdmin")
    body = body_dict()
    # Body FK resolution (priority 4).
    sched = None
    sched_id = body.get("active_discount_schedule_id")
    if sched_id is not None:
        sched = db["schedules"].get(sched_id)
        if sched is None:
            fail("ERR_SCHEDULE_NOT_FOUND", "active_discount_schedule_id does not resolve")
    # Shape rules (priority 9).
    name = req_str(body, "name")
    region = req_str(body, "region")
    capacity = req_decimal(body, "storage_capacity_bushels")
    if capacity <= 0:
        fail("ERR_INVALID_REQUEST", "storage_capacity_bushels must be > 0")
    if sched is None:
        fail("ERR_INVALID_REQUEST", "active_discount_schedule_id is required")
    # Referenced-entity state (priority 11).
    if sched["status"] != "PUBLISHED":
        fail("ERR_SCHEDULE_NOT_PUBLISHED",
             "active_discount_schedule_id must reference a PUBLISHED schedule")
    rec = {
        "id": new_id(),
        "name": name,
        "region": region,
        "storage_capacity_bushels": capacity,
        "active_discount_schedule_id": sched["id"],
        "stored_bushels": Decimal(0),
        "certified_stored_bushels": Decimal(0),
        "receiving_open": True,
    }
    stamp_new(rec)
    db["elevators"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/elevators/<eid>")
def get_elevator(eid):
    require_roles("PlatformAdmin", "OriginationMerchandiser", "LogisticsCoordinator")
    rec = db["elevators"].get(eid)
    if rec is None:
        fail("ERR_ELEVATOR_NOT_FOUND", "elevator not found")
    return success_obj(to_jsonable(rec))


@bp.get("/api/elevators")
def list_elevators():
    require_roles("PlatformAdmin", "OriginationMerchandiser")
    items = sort_created(list(db["elevators"].values()))
    sched_id = request.args.get("active_discount_schedule_id")
    if sched_id is not None:
        items = [e for e in items if e["active_discount_schedule_id"] == sched_id]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(e) for e in page], limit, offset, total)


@bp.get("/api/elevators/<eid>/carry-assessment")
def carry_assessment(eid):
    require_roles("PlatformAdmin", "OriginationMerchandiser", "CrushTrader")
    if eid not in db["elevators"]:
        fail("ERR_ELEVATOR_NOT_FOUND", "elevator not found")
    nearby = request.args.get("nearby_month")
    deferred = request.args.get("deferred_month")
    if not valid_month(nearby) or not valid_month(deferred):
        fail("ERR_INVALID_REQUEST",
             "nearby_month and deferred_month query params must be YYYY-MM")
    months = months_between(nearby, deferred)
    if months <= 0:
        fail("ERR_INVALID_REQUEST", "deferred_month must be after nearby_month")
    nearby_price = asof("BEAN", nearby)
    deferred_price = asof("BEAN", deferred)
    if nearby_price is None or deferred_price is None:
        fail("ERR_NO_MARKET_QUOTE", "no as-of BEAN futures quote for a required leg")
    storage_cost = CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH * months
    signal = (deferred_price - nearby_price) - storage_cost
    decision = "CARRY" if signal > 0 else "FLAT"
    return success_obj({
        "nearby_price_cents": nearby_price,
        "deferred_price_cents": deferred_price,
        "storage_cost_cents_per_bushel": storage_cost,
        "signal_cents_per_bushel": signal,
        "decision": decision,
    })

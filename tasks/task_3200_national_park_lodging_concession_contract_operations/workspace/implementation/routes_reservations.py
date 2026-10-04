"""Reservations: creation, listing, cancel, check-in."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, serialize, paginate, require_fields, parse_dt,
                     round_half_up, touch)
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational
import engine

bp = Blueprint("reservations", __name__)

DEPOSIT_RATE_NUM = 1
DEPOSIT_RATE_DEN = 5  # 0.2
DEPOSIT_CAP_CENTS = 50000
CANCEL_FULL_REFUND_DAYS = 30
TERMINAL_RES = {"CANCELLED", "NO_SHOW", "FULFILLED"}


def get_reservation(cid, rid):
    r = store.reservations.get(rid)
    if not r or r["contract_id"] != cid:
        raise not_found("reservation")
    return r


def _approved_filing(season_id, room_class_id):
    for f in store.filings.values():
        if f["season_id"] == season_id and f["room_class_id"] == room_class_id and f["status"] == "APPROVED":
            return f
    return None


@bp.post("/contracts/<cid>/reservations")
def create_reservation(cid):
    require_role("ConcessionerFrontDesk")
    c = get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["season_id", "room_class_id", "guest_ref", "check_in_date",
                          "check_out_date", "occupancy_band", "expected_contract_version"])
    season = store.seasons.get(body["season_id"])
    if not season or season["contract_id"] != cid:
        raise not_found("season")
    rc = store.room_classes.get(body["room_class_id"])
    if not rc or rc["contract_id"] != cid:
        raise not_found("room_class")
    require_operational(c)
    # entity state
    if season["status"] not in ("PLANNED", "OPEN"):
        raise err("ERR_SEASON_NOT_OPEN", 409, "Season not open for reservations")
    if rc["status"] != "ACTIVE":
        raise err("ERR_ROOM_CLASS_INACTIVE", 409, "Room class inactive")
    band = body["occupancy_band"]
    if band not in ("SOLO", "DOUBLE", "FAMILY"):
        raise err("ERR_INVALID_REQUEST", 400, "invalid occupancy_band")
    mode = body.get("occupancy_mode", "BANDED")
    if mode not in ("BANDED", "ACTUAL_HEADCOUNT"):
        raise err("ERR_INVALID_REQUEST", 400, "invalid occupancy_mode")
    beds = body.get("beds_occupied")
    if mode == "ACTUAL_HEADCOUNT":
        if isinstance(beds, bool) or not isinstance(beds, int) or beds < 1 or beds > 3:
            raise err("ERR_INVALID_REQUEST", 400, "beds_occupied must be 1..3 for ACTUAL_HEADCOUNT")
    if not isinstance(body["guest_ref"], str) or not body["guest_ref"]:
        raise err("ERR_INVALID_REQUEST", 400, "guest_ref required")
    ci = parse_dt(body["check_in_date"], "check_in_date")
    co = parse_dt(body["check_out_date"], "check_out_date")
    # temporal
    if co <= ci:
        raise err("ERR_INVALID_DATE_RANGE", 422, "check_out_date must be after check_in_date")
    nights = (co - ci).days
    if nights < 1:
        raise err("ERR_INVALID_DATE_RANGE", 422, "stay must span at least one night")
    open_dt = parse_dt(season["open_date"])
    close_dt = parse_dt(season["close_date"])
    if ci < open_dt or co > close_dt:
        raise err("ERR_STAY_OUTSIDE_SEASON", 422, "Stay must lie within the season")
    # lottery window
    lottery_open = parse_dt(season["lottery_open_date"])
    window_close = lottery_open + timedelta(hours=season["lottery_window_hours"])
    if store.clock < lottery_open:
        raise err("ERR_LOTTERY_NOT_OPEN", 409, "Lottery window not open")
    # duplicate overlapping live reservation for same guest
    for r in store.reservations.values():
        if r["contract_id"] == cid and r["guest_ref"] == body["guest_ref"] and r["status"] not in TERMINAL_RES:
            rci, rco = parse_dt(r["check_in_date"]), parse_dt(r["check_out_date"])
            if ci < rco and co > rci:
                raise err("ERR_DUPLICATE_RESERVATION", 409, "Guest holds an overlapping reservation")
    # rate resolution from APPROVED filing
    filing = _approved_filing(body["season_id"], body["room_class_id"])
    if not filing:
        raise err("ERR_INVALID_STATE", 409, "No APPROVED rate filing for this season and room class")
    rates = {e["occupancy_band"]: e["nightly_rate_cents"] for e in filing["submitted_rates"]}
    if mode == "BANDED":
        quoted = rates[band]
    else:
        quoted = rates[{1: "SOLO", 2: "DOUBLE", 3: "FAMILY"}[beds]]
    total_charge = quoted * nights
    deposit = min(round_half_up(total_charge * DEPOSIT_RATE_NUM / DEPOSIT_RATE_DEN), DEPOSIT_CAP_CENTS)
    # OCC
    ev = body["expected_contract_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_contract_version must be an integer")
    if ev != c["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", 412, "Stale contract version")
    r = new_entity({
        "contract_id": cid,
        "season_id": body["season_id"],
        "room_class_id": body["room_class_id"],
        "guest_ref": body["guest_ref"],
        "check_in_date": body["check_in_date"],
        "check_out_date": body["check_out_date"],
        "occupancy_band": band,
        "occupancy_mode": mode,
        "beds_occupied": beds if mode == "ACTUAL_HEADCOUNT" else body.get("beds_occupied"),
        "quoted_nightly_rate_cents": quoted,
        "total_charge_cents": total_charge,
        "deposit_cents": deposit,
        "nights": nights,
        "status": "REQUESTED",
        "cancellation_fee_cents": 0,
        "_checked_in": False,
    })
    store.reservations[r["id"]] = r
    touch(c)
    # after window closes: immediate first-come allocation
    if store.clock >= window_close:
        engine.try_immediate_allocate(r)
    return ok(serialize(r), 201)


@bp.get("/contracts/<cid>/reservations")
def list_reservations(cid):
    require_read_role()
    get_contract(cid)
    items = [r for r in store.reservations.values() if r["contract_id"] == cid]
    for key in ("season_id", "room_class_id", "status", "guest_ref"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if str(r.get(key)) == v]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/seasons/<sid>/reservations")
def list_season_reservations(cid, sid):
    require_read_role()
    get_contract(cid)
    s = store.seasons.get(sid)
    if not s or s["contract_id"] != cid:
        raise not_found("season")
    items = [r for r in store.reservations.values() if r["season_id"] == sid]
    st = request.args.get("status")
    if st:
        items = [r for r in items if r["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/room-classes/<rcid>/reservations")
def list_room_class_reservations(cid, rcid):
    require_read_role()
    get_contract(cid)
    rc = store.room_classes.get(rcid)
    if not rc or rc["contract_id"] != cid:
        raise not_found("room_class")
    items = [r for r in store.reservations.values() if r["room_class_id"] == rcid]
    st = request.args.get("status")
    if st:
        items = [r for r in items if r["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/reservations/<rid>")
def get_reservation_route(cid, rid):
    require_read_role()
    get_contract(cid)
    return ok(serialize(get_reservation(cid, rid)))


@bp.post("/contracts/<cid>/reservations/<rid>/cancel")
def cancel_reservation(cid, rid):
    require_role("ConcessionerFrontDesk")
    get_contract(cid)
    r = get_reservation(cid, rid)
    if r["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", 409, "Only REQUESTED or CONFIRMED reservations can be cancelled")
    was_confirmed = r["status"] == "CONFIRMED"
    if r["status"] == "REQUESTED":
        r["cancellation_fee_cents"] = 0
    else:
        ci = parse_dt(r["check_in_date"])
        if (ci - store.clock) < timedelta(days=CANCEL_FULL_REFUND_DAYS):
            r["cancellation_fee_cents"] = r["deposit_cents"]
        else:
            r["cancellation_fee_cents"] = 0
    r["status"] = "CANCELLED"
    touch(r)
    if was_confirmed:
        engine.promote_waitlist(r["season_id"])
    return ok(serialize(r))


@bp.post("/contracts/<cid>/reservations/<rid>/check-in")
def check_in(cid, rid):
    require_role("ConcessionerFrontDesk")
    get_contract(cid)
    r = get_reservation(cid, rid)
    if r["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", 409, "Only CONFIRMED reservations can check in")
    r["_checked_in"] = True
    touch(r)
    return ok(serialize(r))

"""Housing units, seasonal hires, transport vouchers."""
from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, serialize, paginate, require_fields, req_int,
                     parse_dt, touch)
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational
import engine

bp = Blueprint("people", __name__)


def get_unit(cid, uid):
    u = store.housing_units.get(uid)
    if not u or u["contract_id"] != cid:
        raise not_found("housing_unit")
    return u


def get_hire(cid, hid):
    h = store.hires.get(hid)
    if not h or h["contract_id"] != cid:
        raise not_found("hire")
    return h


def get_voucher(cid, vid):
    v = store.vouchers.get(vid)
    if not v or v["contract_id"] != cid:
        raise not_found("voucher")
    return v


# ----- Housing units -----

@bp.post("/contracts/<cid>/housing-units")
def create_unit(cid):
    require_role("ConcessionerHRManager")
    c = get_contract(cid)
    require_operational(c)
    body = request.get_json(silent=True)
    require_fields(body, ["unit_code", "bed_count"])
    if not isinstance(body["unit_code"], str) or not body["unit_code"]:
        raise err("ERR_INVALID_REQUEST", 400, "unit_code required")
    for u in store.housing_units.values():
        if u["contract_id"] == cid and u["unit_code"] == body["unit_code"]:
            raise err("ERR_INVALID_REQUEST", 400, "unit_code must be unique within the contract")
    req_int(body, "bed_count", minimum=1)
    u = new_entity({
        "contract_id": cid,
        "unit_code": body["unit_code"],
        "bed_count": body["bed_count"],
        "status": "AVAILABLE",
    })
    store.housing_units[u["id"]] = u
    return ok(serialize(u), 201)


@bp.get("/contracts/<cid>/housing-units")
def list_units(cid):
    require_read_role()
    get_contract(cid)
    items = [u for u in store.housing_units.values() if u["contract_id"] == cid]
    st = request.args.get("status")
    if st:
        items = [u for u in items if u["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/housing-units/<uid>/take-offline")
def take_offline(cid, uid):
    require_role("ConcessionerHRManager")
    get_contract(cid)
    u = get_unit(cid, uid)
    if u["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", 409, "Unit must be AVAILABLE")
    u["status"] = "OFFLINE"
    touch(u)
    return ok(serialize(u))


# ----- Seasonal hires -----

@bp.post("/contracts/<cid>/seasonal-hires")
def create_hire(cid):
    require_role("ConcessionerHRManager")
    c = get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["season_id", "service_line_id", "employee_ref", "housing_unit_id",
                          "arrival_date", "departure_date"])
    season = store.seasons.get(body["season_id"])
    if not season or season["contract_id"] != cid:
        raise not_found("season")
    sl = store.service_lines.get(body["service_line_id"])
    if not sl or sl["contract_id"] != cid:
        raise not_found("service_line")
    unit = store.housing_units.get(body["housing_unit_id"])
    if not unit or unit["contract_id"] != cid:
        raise not_found("housing_unit")
    require_operational(c)
    if not isinstance(body["employee_ref"], str) or not body["employee_ref"]:
        raise err("ERR_INVALID_REQUEST", 400, "employee_ref required")
    arr = parse_dt(body["arrival_date"], "arrival_date")
    dep = parse_dt(body["departure_date"], "departure_date")
    if dep <= arr:
        raise err("ERR_INVALID_DATE_RANGE", 422, "departure_date must be after arrival_date")
    # hire dates within the season
    open_dt = parse_dt(season["open_date"])
    close_dt = parse_dt(season["close_date"])
    if arr < open_dt or dep > close_dt:
        raise err("ERR_INVALID_DATE_RANGE", 422, "hire dates must lie within the season")
    needs_transport = body.get("needs_transport", True)
    if not isinstance(needs_transport, bool):
        raise err("ERR_INVALID_REQUEST", 400, "needs_transport must be boolean")
    transport_origin = body.get("transport_origin")
    if needs_transport and (not isinstance(transport_origin, str) or not transport_origin):
        raise err("ERR_INVALID_REQUEST", 400, "transport_origin required when needs_transport is true")
    # housing capacity
    if unit["status"] != "AVAILABLE":
        raise err("ERR_UNIT_OFFLINE", 409, "Housing unit is offline")
    if engine.unit_occupied_beds(unit["id"], body["season_id"]) >= unit["bed_count"]:
        raise err("ERR_HOUSING_FULL", 409, "No free bed in the assigned unit")
    h = new_entity({
        "contract_id": cid,
        "season_id": body["season_id"],
        "service_line_id": body["service_line_id"],
        "employee_ref": body["employee_ref"],
        "housing_unit_id": body["housing_unit_id"],
        "arrival_date": body["arrival_date"],
        "departure_date": body["departure_date"],
        "transport_origin": transport_origin if needs_transport else None,
        "needs_transport": needs_transport,
        "transport_voucher_id": None,
        "status": "HIRED",
    })
    if needs_transport:
        v = new_entity({
            "contract_id": cid,
            "hire_id": h["id"],
            "origin": transport_origin,
            "booked_seats": 1,
            "travel_date": body["arrival_date"],
            "status": "BOOKED",
        })
        store.vouchers[v["id"]] = v
        h["transport_voucher_id"] = v["id"]
    store.hires[h["id"]] = h
    return ok(serialize(h), 201)


@bp.get("/contracts/<cid>/seasonal-hires")
def list_hires(cid):
    require_read_role()
    get_contract(cid)
    items = [h for h in store.hires.values() if h["contract_id"] == cid]
    for key in ("season_id", "service_line_id", "housing_unit_id", "status"):
        v = request.args.get(key)
        if v:
            items = [h for h in items if str(h.get(key)) == v]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/seasonal-hires/<hid>/mark-arrived")
def mark_arrived(cid, hid):
    require_role("ConcessionerHRManager")
    get_contract(cid)
    h = get_hire(cid, hid)
    if h["status"] != "HIRED":
        raise err("ERR_INVALID_STATE", 409, "Hire must be HIRED")
    h["status"] = "ARRIVED"
    touch(h)
    v = store.vouchers.get(h.get("transport_voucher_id") or "")
    if v and v["status"] == "BOOKED":
        v["status"] = "USED"
        touch(v)
    return ok(serialize(h))


@bp.post("/contracts/<cid>/seasonal-hires/<hid>/mark-departed")
def mark_departed(cid, hid):
    require_role("ConcessionerHRManager")
    get_contract(cid)
    h = get_hire(cid, hid)
    if h["status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", 409, "Hire must be ARRIVED")
    h["status"] = "DEPARTED"
    touch(h)
    return ok(serialize(h))


@bp.post("/contracts/<cid>/seasonal-hires/<hid>/terminate")
def terminate_hire(cid, hid):
    require_role("ConcessionerHRManager")
    get_contract(cid)
    h = get_hire(cid, hid)
    if h["status"] not in ("HIRED", "ARRIVED"):
        raise err("ERR_INVALID_STATE", 409, "Hire must be HIRED or ARRIVED")
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("reason"), str) or not body["reason"]:
        raise err("ERR_INVALID_REQUEST", 400, "reason required")
    h["status"] = "TERMINATED"
    touch(h)
    v = store.vouchers.get(h.get("transport_voucher_id") or "")
    if v and v["status"] == "BOOKED":
        v["status"] = "VOID"
        touch(v)
    return ok(serialize(h))


# ----- Transport vouchers -----

@bp.post("/contracts/<cid>/transport-vouchers")
def create_voucher(cid):
    require_role("ConcessionerHRManager")
    c = get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["hire_id", "origin", "booked_seats", "travel_date"])
    h = store.hires.get(body["hire_id"])
    if not h or h["contract_id"] != cid:
        raise not_found("hire")
    require_operational(c)
    if not isinstance(body["origin"], str) or not body["origin"]:
        raise err("ERR_INVALID_REQUEST", 400, "origin required")
    req_int(body, "booked_seats", minimum=1)
    td = parse_dt(body["travel_date"], "travel_date")
    season = store.seasons.get(h["season_id"])
    if season:
        if td < parse_dt(season["open_date"]) or td > parse_dt(season["close_date"]):
            raise err("ERR_INVALID_DATE_RANGE", 422, "travel_date must be within the season")
    v = new_entity({
        "contract_id": cid,
        "hire_id": body["hire_id"],
        "origin": body["origin"],
        "booked_seats": body["booked_seats"],
        "travel_date": body["travel_date"],
        "status": "BOOKED",
    })
    store.vouchers[v["id"]] = v
    return ok(serialize(v), 201)


@bp.get("/contracts/<cid>/transport-vouchers")
def list_vouchers(cid):
    require_read_role()
    get_contract(cid)
    items = [v for v in store.vouchers.values() if v["contract_id"] == cid]
    for key in ("hire_id", "status"):
        val = request.args.get(key)
        if val:
            items = [v for v in items if str(v.get(key)) == val]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/transport-vouchers/<vid>/void")
def void_voucher(cid, vid):
    require_role("ConcessionerHRManager")
    get_contract(cid)
    v = get_voucher(cid, vid)
    if v["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", 409, "Voucher must be BOOKED")
    v["status"] = "VOID"
    touch(v)
    return ok(serialize(v))

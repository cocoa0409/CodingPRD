"""Seasons, service lines, room classes routes."""
from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, serialize, paginate, require_fields, req_int,
                     parse_dt, touch, months_between)
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational

bp = Blueprint("setup", __name__)

OPEN_INCIDENT_STATES = {"REPORTED", "UNDER_REVIEW", "CORRECTIVE_PLAN_REQUIRED"}


def get_season(cid, sid):
    s = store.seasons.get(sid)
    if not s or s["contract_id"] != cid:
        raise not_found("season")
    return s


# ----- Seasons -----

@bp.post("/contracts/<cid>/seasons")
def create_season(cid):
    require_role("ConcessionerOpsManager")
    c = get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["year", "open_date", "close_date", "lottery_open_date", "lottery_window_hours"])
    req_int(body, "year", minimum=2000)
    open_dt = parse_dt(body["open_date"], "open_date")
    close_dt = parse_dt(body["close_date"], "close_date")
    lottery_dt = parse_dt(body["lottery_open_date"], "lottery_open_date")
    win = req_int(body, "lottery_window_hours")
    if close_dt <= open_dt:
        raise err("ERR_INVALID_DATE_RANGE", 422, "close_date must be after open_date")
    if lottery_dt >= open_dt or win < 1:
        raise err("ERR_LOTTERY_WINDOW", 422, "lottery_open_date must be strictly before open_date and window >= 1 hour")
    offset = months_between(parse_dt(c["start_date"]), open_dt)
    s = new_entity({
        "contract_id": cid,
        "year": body["year"],
        "open_date": body["open_date"],
        "close_date": body["close_date"],
        "lottery_open_date": body["lottery_open_date"],
        "lottery_window_hours": win,
        "status": "PLANNED",
        "month_offset": offset,
        "_lottery_ran": False,
    })
    store.seasons[s["id"]] = s
    return ok(serialize(s), 201)


@bp.get("/contracts/<cid>/seasons")
def list_seasons(cid):
    require_read_role()
    get_contract(cid)
    items = [s for s in store.seasons.values() if s["contract_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/seasons/<sid>")
def get_season_route(cid, sid):
    require_read_role()
    get_contract(cid)
    return ok(serialize(get_season(cid, sid)))


@bp.post("/contracts/<cid>/seasons/<sid>/reconcile")
def reconcile_season(cid, sid):
    require_role("ConcessionerOpsManager")
    c = get_contract(cid)
    s = get_season(cid, sid)
    if s["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE", 409, "Season must be CLOSED to reconcile")
    for i in store.incidents.values():
        if i["contract_id"] == cid and i["status"] in OPEN_INCIDENT_STATES:
            raise err("ERR_OPEN_ENVIRONMENTAL_INCIDENT", 409, "Open environmental incident blocks reconciliation")
    for h in store.hires.values():
        if h["season_id"] == sid and h["status"] not in ("DEPARTED", "NO_SHOW", "TERMINATED"):
            raise err("ERR_UNRECONCILED_SEASON", 409, "All hires must be terminal to reconcile")
    open_dt, close_dt = parse_dt(s["open_date"]), parse_dt(s["close_date"])
    for r in store.receipts_reports.values():
        if r["contract_id"] != cid:
            continue
        try:
            y, m = int(r["period_month"][:4]), int(r["period_month"][5:7])
        except (ValueError, IndexError):
            continue
        from datetime import datetime, timezone
        month_start = datetime(y, m, 1, tzinfo=timezone.utc)
        if m == 12:
            month_end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
        # overlap of [month_start, month_end) with [open_dt, close_dt]
        if month_start < close_dt and month_end > open_dt:
            if r["status"] != "ACCEPTED":
                raise err("ERR_UNRECONCILED_SEASON", 409, "Overlapping receipts reports must be ACCEPTED")
    s["status"] = "RECONCILED"
    touch(s)
    touch(c)
    return ok(serialize(s))


# ----- Service lines -----

@bp.post("/contracts/<cid>/service-lines")
def create_service_line(cid):
    require_role("AgencyContractingOfficer")
    get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["line_type"])
    lt = body["line_type"]
    if lt not in ("LODGING", "FOOD", "RETAIL", "TOURS"):
        raise err("ERR_INVALID_REQUEST", 400, "invalid line_type")
    sl = new_entity({
        "contract_id": cid,
        "line_type": lt,
        "authorized": body.get("authorized", True),
        "separate_reporting_required": body.get("separate_reporting_required", True),
        "status": "AUTHORIZED",
    })
    store.service_lines[sl["id"]] = sl
    return ok(serialize(sl), 201)


@bp.get("/contracts/<cid>/service-lines")
def list_service_lines(cid):
    require_read_role()
    get_contract(cid)
    items = [s for s in store.service_lines.values() if s["contract_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/service-lines/<lid>/suspend")
def suspend_line(cid, lid):
    require_role("AgencyContractingOfficer")
    get_contract(cid)
    sl = store.service_lines.get(lid)
    if not sl or sl["contract_id"] != cid:
        raise not_found("service_line")
    if sl["status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", 409, "Line must be AUTHORIZED")
    sl["status"] = "SUSPENDED"
    touch(sl)
    return ok(serialize(sl))


@bp.post("/contracts/<cid>/service-lines/<lid>/reinstate")
def reinstate_line(cid, lid):
    require_role("AgencyContractingOfficer")
    get_contract(cid)
    sl = store.service_lines.get(lid)
    if not sl or sl["contract_id"] != cid:
        raise not_found("service_line")
    if sl["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", 409, "Line must be SUSPENDED")
    sl["status"] = "AUTHORIZED"
    touch(sl)
    return ok(serialize(sl))


# ----- Room classes -----

@bp.post("/contracts/<cid>/room-classes")
def create_room_class(cid):
    require_role("ConcessionerOpsManager")
    get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["code", "total_rooms", "peak_season_months"])
    if not isinstance(body["code"], str) or not body["code"]:
        raise err("ERR_INVALID_REQUEST", 400, "code required")
    for rc in store.room_classes.values():
        if rc["contract_id"] == cid and rc["code"] == body["code"]:
            raise err("ERR_INVALID_REQUEST", 400, "code must be unique within the contract")
    req_int(body, "total_rooms", minimum=1)
    months = body["peak_season_months"]
    if (not isinstance(months, list) or not months or
            any(isinstance(m, bool) or not isinstance(m, int) or m < 1 or m > 12 for m in months)):
        raise err("ERR_INVALID_REQUEST", 400, "peak_season_months must be an array of months 1-12")
    rc = new_entity({
        "contract_id": cid,
        "code": body["code"],
        "total_rooms": body["total_rooms"],
        "peak_season_months": list(months),
        "status": "ACTIVE",
    })
    store.room_classes[rc["id"]] = rc
    return ok(serialize(rc), 201)


@bp.get("/contracts/<cid>/room-classes")
def list_room_classes(cid):
    require_read_role()
    get_contract(cid)
    items = [r for r in store.room_classes.values() if r["contract_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)

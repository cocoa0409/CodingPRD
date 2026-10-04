"""Airports, partner agreements, lanes."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, fmt_dt, _parse_dt
from errors import ApiError
from middleware import require_roles, body, require_field, pagination_params, paginate
from models import new_entity, touch
from response import success
from serializers import present, present_list
import services

bp = Blueprint("airports", __name__)


def _sorted(collection):
    return sorted(collection, key=lambda e: (e["created_at"], e["id"]))


# ---------------- airports ----------------

@bp.post("/airports")
@require_roles("OpsAdmin")
def create_airport():
    data = body()
    iata = require_field(data, "iata_code")
    name = require_field(data, "name")
    city = require_field(data, "city")
    state_code = require_field(data, "state_code")
    if not isinstance(iata, str) or len(iata) != 3 or not iata.isalpha() or not iata.isupper():
        raise ApiError("ERR_VALIDATION", 400, "iata_code must be a 3-letter uppercase code")
    for a in store.airports.values():
        if a["iata_code"] == iata:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "iata_code already in use")
    a = new_entity()
    a.update({
        "iata_code": iata,
        "name": name,
        "city": city,
        "state_code": state_code,
        "status": "ONBOARDING",
    })
    store.airports[a["id"]] = a
    return success(present(a), status_code=201)


@bp.get("/airports")
@require_roles("OpsAdmin", "PartnerManager", "ComplianceOfficer")
def list_airports():
    limit, offset = pagination_params()
    items = _sorted(store.airports.values())
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), status_code=200, is_array=True, pagination=meta)


@bp.get("/airports/<aid>")
@require_roles("OpsAdmin", "PartnerManager", "ComplianceOfficer")
def get_airport(aid):
    a = store.airports.get(aid)
    if a is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    return success(present(a))


@bp.post("/airports/<aid>/suspend")
@require_roles("OpsAdmin")
def suspend_airport(aid):
    a = store.airports.get(aid)
    if a is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Airport is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    ag = services.agreement_by_status(aid, ("ACTIVE",))
    if ag is not None:
        ag["status"] = "SUSPENDED"
        touch(ag)
        for lane in store.lanes.values():
            if lane["agreement_id"] == ag["id"] and lane["status"] == "OPEN":
                lane["status"] = "MAINTENANCE"
                touch(lane)
        services.recompute_lane_capacity(ag)
        touch(ag)
    return success(present(a))


@bp.post("/airports/<aid>/activate")
@require_roles("OpsAdmin")
def activate_airport(aid):
    a = store.airports.get(aid)
    if a is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    if a["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Airport is not SUSPENDED")
    ag = services.agreement_by_status(aid, ("ACTIVE", "SUSPENDED"))
    if ag is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "Airport has no agreement in ACTIVE or SUSPENDED status")
    a["status"] = "ACTIVE"
    touch(a)
    if ag["status"] == "SUSPENDED":
        ag["status"] = "ACTIVE"
        touch(ag)
    return success(present(a))


# ---------------- partner agreements ----------------

@bp.post("/partner-agreements")
@require_roles("PartnerManager")
def create_agreement():
    data = body()
    airport_id = require_field(data, "airport_id")
    rev = require_field(data, "rev_share_rate")
    sub_rate = require_field(data, "subscription_share_rate")
    monthly_minimum = require_field(data, "monthly_minimum_cents")
    federal = require_field(data, "federal_integration")
    seats = require_field(data, "staffing_footprint_seats")
    term = require_field(data, "term_months")
    effective_from = require_field(data, "effective_from")
    airport = store.airports.get(airport_id)
    if airport is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    from decimal import Decimal, InvalidOperation
    try:
        rev_d = Decimal(str(rev))
        sub_d = Decimal(str(sub_rate))
    except (InvalidOperation, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "Rates must be numeric")
    if rev_d <= 0 or rev_d > services.MAX_RATE or sub_d <= 0 or sub_d > services.MAX_RATE:
        raise ApiError("ERR_VALIDATION", 400, "Rates must be within (0, 0.30]")
    if not isinstance(monthly_minimum, int) or monthly_minimum < 0:
        raise ApiError("ERR_VALIDATION", 400, "monthly_minimum_cents must be an integer >= 0")
    if not isinstance(seats, int) or seats < 1:
        raise ApiError("ERR_VALIDATION", 400, "staffing_footprint_seats must be >= 1")
    if not isinstance(term, int) or term < 1 or term > 120:
        raise ApiError("ERR_VALIDATION", 400, "term_months must be within 1..120")
    try:
        eff_from = _parse_dt(effective_from)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "effective_from must be an ISO datetime")
    if services.active_agreement_for_airport(airport_id) is not None:
        raise ApiError("ERR_DUPLICATE_AGREEMENT", 409,
                       "Airport already has a DRAFT or ACTIVE agreement")
    a = new_entity()
    a.update({
        "airport_id": airport_id,
        "rev_share_rate": rev,
        "subscription_share_rate": sub_rate,
        "monthly_minimum_cents": monthly_minimum,
        "federal_integration": bool(federal),
        "staffing_footprint_seats": seats,
        "term_months": term,
        "status": "DRAFT",
        "effective_from": fmt_dt(eff_from),
        "effective_to": None,
        "lane_capacity": 0,
    })
    store.partner_agreements[a["id"]] = a
    return success(present(a), status_code=201)


@bp.get("/partner-agreements")
@require_roles("OpsAdmin", "PartnerManager")
def list_agreements():
    limit, offset = pagination_params()
    airport_id = request.args.get("airport_id")
    items = _sorted(store.partner_agreements.values())
    if airport_id is not None:
        items = [a for a in items if a["airport_id"] == airport_id]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/partner-agreements/<aid>")
@require_roles("OpsAdmin", "PartnerManager")
def get_agreement(aid):
    a = store.partner_agreements.get(aid)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Agreement not found")
    return success(_agreement_view(a))


def _add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    import calendar
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def _agreement_view(a):
    return present(a)


@bp.post("/partner-agreements/<aid>/activate")
@require_roles("PartnerManager")
def activate_agreement(aid):
    a = store.partner_agreements.get(aid)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Agreement not found")
    if a["status"] == "DRAFT":
        if store.now() < _parse_dt(a["effective_from"]):
            raise ApiError("ERR_AGREEMENT_NOT_YET_EFFECTIVE", 409,
                           "Agreement is not yet effective")
        a["effective_to"] = fmt_dt(_add_months(_parse_dt(a["effective_from"]), a["term_months"]))
        a["status"] = "ACTIVE"
        touch(a)
        airport = store.airports.get(a["airport_id"])
        if airport is not None and airport["status"] == "ONBOARDING":
            airport["status"] = "ACTIVE"
            touch(airport)
    elif a["status"] == "SUSPENDED":
        if a.get("effective_to") and store.now() >= _parse_dt(a["effective_to"]):
            raise ApiError("ERR_AGREEMENT_EXPIRED", 409, "Agreement has expired")
        a["status"] = "ACTIVE"
        touch(a)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement cannot be activated from this state")
    return success(_agreement_view(a))


@bp.post("/partner-agreements/<aid>/suspend")
@require_roles("PartnerManager")
def suspend_agreement(aid):
    a = store.partner_agreements.get(aid)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Agreement not found")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    for lane in store.lanes.values():
        if lane["agreement_id"] == a["id"] and lane["status"] == "OPEN":
            lane["status"] = "MAINTENANCE"
            touch(lane)
    services.recompute_lane_capacity(a)
    touch(a)
    return success(_agreement_view(a))


@bp.post("/partner-agreements/<aid>/terminate")
@require_roles("PartnerManager")
def terminate_agreement(aid):
    a = store.partner_agreements.get(aid)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Agreement not found")
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not ACTIVE or SUSPENDED")
    a["status"] = "TERMINATED"
    touch(a)
    services.close_all_lanes_of_agreement(a)
    touch(a)
    return success(_agreement_view(a))


# ---------------- lanes ----------------

@bp.post("/lanes")
@require_roles("OpsAdmin")
def create_lane():
    data = body()
    airport_id = require_field(data, "airport_id")
    agreement_id = require_field(data, "agreement_id")
    terminal = require_field(data, "terminal")
    position_index = require_field(data, "position_index")
    open_time = require_field(data, "open_time")
    close_time = require_field(data, "close_time")
    capacity_hours = require_field(data, "capacity_hours")
    airport = store.airports.get(airport_id)
    if airport is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    ag = store.partner_agreements.get(agreement_id)
    if ag is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Agreement not found")
    if ag["airport_id"] != airport_id:
        raise ApiError("ERR_VALIDATION", 400, "Agreement does not belong to the named airport")
    if not isinstance(position_index, int) or position_index < 1:
        raise ApiError("ERR_VALIDATION", 400, "position_index must be > 0")
    if not _valid_hhmm(open_time) or not _valid_hhmm(close_time) or close_time <= open_time:
        raise ApiError("ERR_VALIDATION", 400, "close_time must be strictly after open_time (HH:MM)")
    if not isinstance(capacity_hours, int) or capacity_hours < 1 or capacity_hours > 24:
        raise ApiError("ERR_VALIDATION", 400, "capacity_hours must be within 1..24")
    lane = new_entity()
    lane.update({
        "airport_id": airport_id,
        "agreement_id": agreement_id,
        "terminal": terminal,
        "position_index": position_index,
        "open_time": open_time,
        "close_time": close_time,
        "capacity_hours": capacity_hours,
        "status": "PLANNED",
    })
    store.lanes[lane["id"]] = lane
    return success(present(lane), status_code=201)


def _valid_hhmm(s):
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        return False
    try:
        h = int(s[:2]); m = int(s[3:])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


@bp.get("/lanes")
@require_roles("OpsAdmin", "PartnerManager", "Ambassador", "Member")
def list_lanes():
    limit, offset = pagination_params()
    items = _sorted(store.lanes.values())
    ag = request.args.get("agreement_id")
    ap = request.args.get("airport_id")
    if ag is not None:
        items = [l for l in items if l["agreement_id"] == ag]
    if ap is not None:
        items = [l for l in items if l["airport_id"] == ap]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/lanes/<lid>")
@require_roles("OpsAdmin", "PartnerManager", "Ambassador", "Member")
def get_lane(lid):
    lane = store.lanes.get(lid)
    if lane is None:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "Lane not found")
    return success(present(lane))


@bp.post("/lanes/<lid>/open")
@require_roles("OpsAdmin")
def open_lane(lid):
    lane = store.lanes.get(lid)
    if lane is None:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "Lane not found")
    if lane["status"] not in ("PLANNED", "MAINTENANCE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Lane is not PLANNED or MAINTENANCE")
    ag = store.partner_agreements.get(lane["agreement_id"])
    if ag is None or ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement is not ACTIVE")
    if lane["status"] == "PLANNED":
        projected = ag["lane_capacity"] + lane["capacity_hours"]
    else:
        # MAINTENANCE lanes already count; re-opening leaves the total unchanged
        projected = ag["lane_capacity"]
    if projected > ag["staffing_footprint_seats"] * services.AMBASSADOR_SEAT_HOURS:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                       "Opening the lane would exceed the staffing footprint")
    lane["status"] = "OPEN"
    touch(lane)
    services.recompute_lane_capacity(ag)
    touch(ag)
    return success(present(lane))


@bp.post("/lanes/<lid>/close")
@require_roles("OpsAdmin")
def close_lane(lid):
    lane = store.lanes.get(lid)
    if lane is None:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "Lane not found")
    data = body()
    mode = require_field(data, "mode")
    if mode not in ("MAINTENANCE", "CLOSED"):
        raise ApiError("ERR_VALIDATION", 400, "mode must be MAINTENANCE or CLOSED")
    if mode == "MAINTENANCE":
        if lane["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Lane is not OPEN")
        lane["status"] = "MAINTENANCE"
    else:
        if lane["status"] not in ("OPEN", "MAINTENANCE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Lane is not OPEN or MAINTENANCE")
        lane["status"] = "CLOSED"
    touch(lane)
    ag = store.partner_agreements.get(lane["agreement_id"])
    if ag is not None:
        services.recompute_lane_capacity(ag)
        touch(ag)
    return success(present(lane))

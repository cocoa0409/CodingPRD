"""Settlement periods and lines."""

from flask import Blueprint, request

from db import DB, CLOCK, new_id, stamp_new, touch, fmt_ts, parse_iso
from errors import (
    not_found, invalid_request, invalid_state, business,
    ERR_PERIOD_NOT_CLOSABLE, ERR_SOD_CONFLICT, ERR_LINE_ALREADY_SWEPT,
)
from middleware import require_auth
from response import ok_obj
from routes._common import list_response
from services.calculations import settle_fee
from services.serialize import public
from services.validate import body_json, req_string, parse_iso_field

bp = Blueprint("settlement", __name__)

SETTLE_READ = {"SettlementClerk", "FederationFinance"}


def _get_period(periodId):
    p = DB.settlement_periods.get(periodId)
    if p is None:
        raise not_found("settlement period not found")
    return p


def _get_line(lineId):
    l = DB.settlement_lines.get(lineId)
    if l is None:
        raise not_found("settlement line not found")
    return l


@bp.post("/motor-club/settlement-periods")
def create_period():
    require_auth({"SettlementClerk"})
    data = body_json()
    servicing_club_id = req_string(data, "servicing_club_id")
    if "period_start_date" not in data or data["period_start_date"] is None:
        raise invalid_request("missing required field: period_start_date")
    if "period_end_date" not in data or data["period_end_date"] is None:
        raise invalid_request("missing required field: period_end_date")
    start_dt = parse_iso_field(data["period_start_date"], "period_start_date")
    end_dt = parse_iso_field(data["period_end_date"], "period_end_date")
    if end_dt <= start_dt:
        raise invalid_request("period_end_date must be after period_start_date")
    club = DB.clubs.get(servicing_club_id)
    if club is None:
        raise not_found("servicing club not found")
    period = {
        "id": new_id(),
        "servicing_club_id": servicing_club_id,
        "period_start_date": data["period_start_date"],
        "period_end_date": data["period_end_date"],
        "status": "OPEN",
        "closed_by": "",
        "total_foreign_call_count": 0,
        "total_gross_cents": 0,
        "closed_at": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    stamp_new(period)
    DB.settlement_periods[period["id"]] = period
    return ok_obj(public(period), 201)


@bp.get("/motor-club/settlement-periods")
def list_periods():
    require_auth(SETTLE_READ)
    sc = request.args.get("servicing_club_id")
    status = request.args.get("status")

    def filt(p):
        if sc is not None and p["servicing_club_id"] != sc:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    return list_response(list(DB.settlement_periods.values()), filt)


@bp.get("/motor-club/settlement-periods/<periodId>")
def get_period(periodId):
    require_auth(SETTLE_READ)
    return ok_obj(public(_get_period(periodId)))


@bp.post("/motor-club/settlement-periods/<periodId>/close")
def close_period(periodId):
    user_id, _ = require_auth({"SettlementClerk"})
    p = _get_period(periodId)
    if p["status"] != "OPEN":
        raise invalid_state("close is permitted only from OPEN")
    now = CLOCK.now()
    if now < p["_end_dt"]:
        raise business(ERR_PERIOD_NOT_CLOSABLE,
                       "period cannot be closed before period_end_date")

    # sweep with pinned evaluation order
    lines = [l for l in DB.settlement_lines.values()
             if l["servicing_club_id"] == p["servicing_club_id"]]
    lines = [l for l in lines if not l["excluded"]]
    lines = [l for l in lines if l["status"] == "PENDING"]

    def in_window(l):
        call = DB.service_calls.get(l["service_call_id"])
        if call is None or "_completed_dt" not in call:
            return False
        return p["_start_dt"] <= call["_completed_dt"] < p["_end_dt"]

    lines = [l for l in lines if in_window(l)]

    def sort_key(l):
        call = DB.service_calls.get(l["service_call_id"])
        return (call["_completed_dt"], call["_created_dt"])

    lines.sort(key=sort_key)

    total_gross = 0
    for l in lines:
        l["status"] = "SWEPT"
        l["settlement_period_id"] = p["id"]
        touch(l)
        total_gross += l["gross_amount_cents"]

    p["status"] = "CLOSED"
    p["closed_by"] = user_id
    p["total_foreign_call_count"] = len(lines)
    p["total_gross_cents"] = total_gross
    p["closed_at"] = fmt_ts(now)
    touch(p)
    return ok_obj(public(p))


@bp.post("/motor-club/settlement-periods/<periodId>/assess")
def assess_period(periodId):
    user_id, _ = require_auth({"FederationFinance"})
    p = _get_period(periodId)
    if p["status"] != "CLOSED":
        raise invalid_state("assess is permitted only from CLOSED")
    if p["closed_by"] == user_id:
        raise business(ERR_SOD_CONFLICT,
                       "assessor must differ from the closing clerk")
    swept = [l for l in DB.settlement_lines.values()
             if l.get("settlement_period_id") == p["id"] and l["status"] == "SWEPT"]

    def sort_key(l):
        call = DB.service_calls.get(l["service_call_id"])
        return (call["_completed_dt"], call["_created_dt"])

    swept.sort(key=sort_key)
    for l in swept:
        fee = settle_fee(l["gross_amount_cents"])
        l["assessed_fee_cents"] = fee
        l["assessed_net_cents"] = l["gross_amount_cents"] - fee
        l["status"] = "ASSESSED"
        touch(l)
    p["status"] = "ASSESSED"
    touch(p)
    return ok_obj(public(p))


@bp.get("/motor-club/settlement-periods/<pid>/settlementLines")
def list_lines_of_period(pid):
    require_auth(SETTLE_READ)
    _get_period(pid)
    rows = [l for l in DB.settlement_lines.values()
            if l.get("settlement_period_id") == pid]
    return list_response(rows)


@bp.get("/motor-club/settlement-lines")
def list_lines():
    require_auth(SETTLE_READ)
    home_club_id = request.args.get("home_club_id")
    servicing_club_id = request.args.get("servicing_club_id")
    settlement_period_id = request.args.get("settlement_period_id")
    service_call_id = request.args.get("service_call_id")
    status = request.args.get("status")

    def filt(l):
        if home_club_id is not None and l["home_club_id"] != home_club_id:
            return False
        if servicing_club_id is not None and l["servicing_club_id"] != servicing_club_id:
            return False
        if settlement_period_id is not None and l.get("settlement_period_id") != settlement_period_id:
            return False
        if service_call_id is not None and l["service_call_id"] != service_call_id:
            return False
        if status is not None and l["status"] != status:
            return False
        return True

    return list_response(list(DB.settlement_lines.values()), filt)


@bp.get("/motor-club/settlement-lines/<lineId>")
def get_line(lineId):
    require_auth(SETTLE_READ)
    return ok_obj(public(_get_line(lineId)))


@bp.post("/motor-club/settlement-lines/<lineId>/reverse")
def reverse_line(lineId):
    require_auth({"FederationFinance"})
    l = _get_line(lineId)
    if l["status"] != "PENDING":
        raise business(ERR_LINE_ALREADY_SWEPT,
                       "only PENDING lines can be reversed")
    l["status"] = "REVERSED"
    touch(l)
    return ok_obj(public(l))

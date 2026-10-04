"""Uptime contract endpoints (PRD section 3.10)."""

import re
from datetime import date

from flask import Blueprint

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, check_occ, body, req_field, as_str,
                  as_int, as_num, as_enum, parse_dt, find, ok)

bp = Blueprint("uptime", __name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_iso_date(v, f):
    s = as_str(v, f)
    if not _DATE_RE.match(s):
        raise ApiError(E.ERR_VALIDATION, 400,
                       "field %s must be a YYYY-MM-DD date" % f)
    try:
        date.fromisoformat(s)
    except ValueError:
        raise ApiError(E.ERR_VALIDATION, 400,
                       "field %s must be a valid YYYY-MM-DD date" % f)
    return s


@bp.post("/evfleet/uptime-contracts")
def create_uptime_contract():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    fleet_customer_id = as_str(req_field(b, "fleet_customer_id"), "fleet_customer_id")
    find(DB.customers, fleet_customer_id, "fleet customer")
    committed = as_num(req_field(b, "committed_uptime_pct"), "committed_uptime_pct")
    if not (calc.D(0) < calc.D(committed) <= calc.D(100)):
        raise ApiError(E.ERR_VALIDATION, 400,
                       "committed_uptime_pct must be > 0 and <= 100")
    fee = as_int(req_field(b, "monthly_service_fee_cents"),
                 "monthly_service_fee_cents")
    if fee <= 0:
        raise ApiError(E.ERR_VALIDATION, 400,
                       "monthly_service_fee_cents must be > 0")
    pro_rating = as_enum(req_field(b, "pro_rating"),
                         {"ROUTE_DAY", "VEHICLE_HOUR"}, "pro_rating")
    msd = _check_iso_date(req_field(b, "measurement_start_date"),
                          "measurement_start_date")
    e = {
        "fleet_customer_id": fleet_customer_id,
        "committed_uptime_pct": committed,
        "monthly_service_fee_cents": fee,
        "pro_rating": pro_rating,
        "measurement_start_date": msd,
        "downtime_events": [],
        "last_closed_month": None,
        "last_uptime_pct": None,
        "last_credit_cents": None,
        "lifetime_credit_cents": 0,
        "_events_parsed": [],
    }
    store.stamp_new(e)
    DB.contracts[e["id"]] = e
    return ok(store.public(e), 201)


@bp.post("/evfleet/uptime-contracts/<cid>/downtime-events")
def append_downtime_event(cid):
    _, role = auth()
    require_role(role, {"TelematicsIngestion"})
    contract = find(DB.contracts, cid, "uptime contract")
    b = body()
    vehicle_id = as_str(req_field(b, "vehicle_id"), "vehicle_id")
    # priority 3: body FK existence
    find(DB.vehicles, vehicle_id, "vehicle")
    # priority 5: OCC on UptimeContract.version
    expected = as_int(req_field(b, "expected_uptime_contract_version"),
                      "expected_uptime_contract_version")
    check_occ(expected, contract["version"])
    started_raw = as_str(req_field(b, "started_at"), "started_at")
    started = parse_dt(started_raw, "started_at")
    ended_raw = b.get("ended_at")
    ended = None
    if ended_raw is not None:
        as_str(ended_raw, "ended_at")
        ended = parse_dt(ended_raw, "ended_at")
    contract["downtime_events"].append({
        "vehicle_id": vehicle_id,
        "started_at": started_raw,
        "ended_at": ended_raw,
    })
    contract["_events_parsed"].append({
        "vehicle_id": vehicle_id,
        "start": started,
        "end": ended,
    })
    store.touch(contract)
    return ok(store.public(contract), 201)


@bp.post("/evfleet/uptime-contracts/<cid>/close-month")
def close_month(cid):
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    contract = find(DB.contracts, cid, "uptime contract")
    b = body()
    month = req_field(b, "month")
    pm = calc.parse_month(month)
    # priority 6: close-month chronology and the measurable-fleet precondition
    if pm is not None:
        msd = contract["measurement_start_date"]
        meas_month = (int(msd[:4]), int(msd[5:7]))
        if pm < meas_month:
            raise ApiError(E.ERR_MONTH_OUT_OF_ORDER, 409,
                           "month precedes the measurement_start_date month")
        lc = contract["last_closed_month"]
        if lc is not None:
            lcp = (int(lc[:4]), int(lc[5:7]))
            if pm == lcp:
                raise ApiError(E.ERR_MONTH_ALREADY_CLOSED, 409,
                               "month %s was already closed" % month)
            if pm < lcp:
                raise ApiError(E.ERR_MONTH_OUT_OF_ORDER, 409,
                               "months must close strictly chronologically")
        if len(calc.in_service_fleet(contract)) == 0:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "no in-service fleet to measure")
    # priority 9: month well-formed YYYY-MM
    if pm is None:
        raise ApiError(E.ERR_WINDOW_INVALID, 400,
                       "month must be a YYYY-MM string")
    uptime, credit = calc.close_month_credit(contract, month)
    contract["last_closed_month"] = month
    contract["last_uptime_pct"] = float(uptime)
    contract["last_credit_cents"] = credit
    contract["lifetime_credit_cents"] += credit
    store.touch(contract)
    return ok(store.public(contract), 200)

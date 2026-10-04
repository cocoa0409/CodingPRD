"""SellThroughReport routes: file weekly report (computes both cannibalization
variants), read, list."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from domain import (
    SEASONAL_LIFT, round4, get_report, ser_report,
)
from errors import (
    ApiError, ERR_RETAILER_NOT_FOUND, ERR_PROGRAM_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH, ERR_REPORT_WEEK_OUT_OF_WINDOW, ERR_DUPLICATE_RESOURCE,
)
from middleware import authorize, ROLE_RETAILER, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_dt

bp = Blueprint("reports", __name__)


@bp.post("/confection/sell-through-reports")
def create_report():
    data = json_body()
    retailer_id = v_str(data, "retailer_id")
    program_id = v_str(data, "program_id")
    week_dt, week_raw = v_dt(data, "week_of_on")
    seasonal_sold = v_int(data, "seasonal_units_sold", min_v=0)
    seasonal_on_hand = v_int(data, "seasonal_units_on_hand", min_v=0)
    everyday_sold = v_int(data, "everyday_units_sold", min_v=0)

    actor = authorize(ROLE_RETAILER)

    # Ownership (priority 4) precedes body-FK existence (priority 5).
    if retailer_id != actor.user_id:
        raise ApiError(403, ERR_OWNERSHIP_MISMATCH,
                       "retailer_id must equal the acting X-User-ID")

    # Body FKs in declared input order: retailer_id, program_id.
    retailer = db.retailers.get(retailer_id)
    if retailer is None:
        raise ApiError(404, ERR_RETAILER_NOT_FOUND,
                       "RetailerAccount %s does not exist" % retailer_id)
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError(404, ERR_PROGRAM_NOT_FOUND,
                       "SeasonalProgram %s does not exist" % program_id)

    # Temporal (priority 9): week_of_on inside [on_shelf_on, pull_on], inclusive.
    if not (program["_on_shelf_dt"] <= week_dt <= program["_pull_dt"]):
        raise ApiError(422, ERR_REPORT_WEEK_OUT_OF_WINDOW,
                       "week_of_on must lie inside [on_shelf_on, pull_on]")

    # Structural (priority 10): the (retailer, program, week) triple is unique.
    for r in db.reports.values():
        if (r["retailer_id"] == retailer_id and r["program_id"] == program_id
                and r["_week_dt"] == week_dt):
            raise ApiError(409, ERR_DUPLICATE_RESOURCE,
                           "a report already exists for this retailer, program and week")

    # cannibalization_index: both variants, 4 decimal places, round half-up.
    baseline = Decimal(retailer["everyday_baseline_weekly_units"])
    sold = Decimal(everyday_sold)
    raw = round4(sold / baseline)
    adjusted = round4(sold / (baseline * SEASONAL_LIFT[program["season_code"]]))

    report = _create_entity(db.reports, {
        "retailer_id": retailer_id,
        "program_id": program_id,
        "week_of_on": week_raw,
        "_week_dt": week_dt,
        "seasonal_units_sold": seasonal_sold,
        "seasonal_units_on_hand": seasonal_on_hand,
        "everyday_units_sold": everyday_sold,
        "cannibalization_raw": float(raw),
        "cannibalization_adjusted": float(adjusted),
    })
    return created(ser_report(report))


@bp.get("/confection/sell-through-reports/<report_id>")
def read_report(report_id):
    authorize(*ALL_ROLES)
    return ok(ser_report(get_report(report_id)))


@bp.get("/confection/sell-through-reports")
def list_reports():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.reports.values())
    for param in ("retailer_id", "program_id"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_report(r) for r in page], total, limit, offset)

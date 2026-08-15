"""AnnualStateReport endpoints."""
from flask import Blueprint, request

from db import store, new_id, stamp, touch
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default, query_int
from response import ok, ok_list
from serializers import ser_annual
from services import official_selector
from util import D0, round3, is_int

bp = Blueprint("annual", __name__)


@bp.post("/annual-state-reports")
def create_annual_report():
    require_roles("WaterMaster")
    b = body()
    wy = b.get("water_year")
    if not is_int(wy):
        raise err("ERR_INVALID_REQUEST", "water_year must be an integer")
    if wy not in store.closed_years:
        raise err("ERR_WATER_YEAR_NOT_CLOSED", "Water year has not been closed")
    if any(r["water_year"] == wy for r in store.annual_reports.values()):
        raise err("ERR_ANNUAL_REPORT_EXISTS", "An AnnualStateReport already exists for the water year")
    year_reports = [r for r in store.reports.values()
                    if r["status"] == "VERIFIED" and r["water_year"] == wy]
    total_extracted = D0
    total_fees = 0
    for r in year_reports:
        total_extracted += r["reported_af"]
        total_fees += r["fee_cents"]
    year_assessments = [a for a in store.assessments.values() if a["water_year"] == wy]
    overdraft_count = sum(1 for a in year_assessments if a["reason"] == "OVERDRAFT")
    assessed_cents = sum(a["amount_cents"] for a in year_assessments)
    collected_cents = sum(a["paid_amount_cents"] for a in year_assessments
                          if a["status"] == "PAID")
    sel = official_selector()
    r = {
        "id": new_id(),
        "water_year": wy,
        "total_extracted_af": round3(total_extracted),
        "verified_report_count": len(year_reports),
        "overdraft_assessment_count": overdraft_count,
        "penalties_assessed_cents": assessed_cents,
        "penalties_collected_cents": collected_cents,
        "total_pumping_fees_cents": total_fees,
        "final_basin_condition": sel["condition"] if sel is not None else None,
        "avg_depth_ft": sel["rolling_mean_depth_ft"] if sel is not None else None,
        "status": "DRAFT",
    }
    stamp(r)
    store.annual_reports[r["id"]] = r
    return ok(ser_annual(r), status=201)


@bp.get("/annual-state-reports")
def list_annual_reports():
    require_roles(*ALL_ROLES)
    items = list(store.annual_reports.values())
    wy = query_int("water_year")
    if wy is not None:
        items = [r for r in items if r["water_year"] == wy]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_annual(r) for r in page], pg)


@bp.post("/annual-state-reports/<report_id>/submit")
def submit_annual_report(report_id):
    require_roles("WaterMaster")
    r = store.annual_reports.get(report_id)
    if r is None:
        raise err("ERR_ANNUAL_REPORT_NOT_FOUND", "No AnnualStateReport with the given id")
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_ANNUAL_REPORT_STATE", "submit requires status DRAFT")
    r["status"] = "SUBMITTED"
    r["version"] += 1
    touch(r)
    return ok(ser_annual(r))


@bp.post("/annual-state-reports/<report_id>/acknowledge")
def acknowledge_annual_report(report_id):
    require_roles("StateRegulator")
    r = store.annual_reports.get(report_id)
    if r is None:
        raise err("ERR_ANNUAL_REPORT_NOT_FOUND", "No AnnualStateReport with the given id")
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_ANNUAL_REPORT_STATE", "acknowledge requires status SUBMITTED")
    r["status"] = "ACKNOWLEDGED"
    r["version"] += 1
    touch(r)
    return ok(ser_annual(r))

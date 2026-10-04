"""Daily throughput reports."""

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_invalid_state, err_not_found, err_invalid_request
from helpers import (body_json, new_entity, parse_date, require_fields, success_list,
                     success_obj, to_decimal, touch)
from calculations import compute_report_fields
from serializers import report_out

bp = Blueprint("reports", __name__)

PO = ["PlantOperator"]
READERS = ["PlantOperator", "EnergyTrader", "EnvironmentalOfficer", "Regulator"]


def _validate_inputs(waste, hv, hours):
    if waste <= 0:
        raise err_invalid_request("waste_processed_tonnes must be > 0")
    if hv <= 0:
        raise err_invalid_request("avg_heating_value_mj_per_kg must be > 0")
    if hours <= 0 or hours > 24:
        raise err_invalid_request("operating_hours must be > 0 and <= 24")


@bp.post("/wte/daily-throughput-reports")
def create_report():
    require_role(PO)
    b = body_json()
    require_fields(b, ["report_date", "waste_processed_tonnes",
                       "avg_heating_value_mj_per_kg", "operating_hours"])
    report_date = parse_date(b["report_date"], "report_date")
    for r in store.throughput_reports.values():
        if r["report_date"] == report_date:
            raise err_422("ERR_DUPLICATE_REPORT_DATE", "report_date already exists")
    waste = to_decimal(b["waste_processed_tonnes"], "waste_processed_tonnes")
    hv = to_decimal(b["avg_heating_value_mj_per_kg"], "avg_heating_value_mj_per_kg")
    hours = to_decimal(b["operating_hours"], "operating_hours")
    _validate_inputs(waste, hv, hours)
    r = new_entity({
        "report_date": report_date,
        "waste_processed_tonnes": waste,
        "avg_heating_value_mj_per_kg": hv,
        "operating_hours": hours,
        "status": "DRAFT",
    })
    compute_report_fields(r, list(store.boilers.values()))
    store.throughput_reports[r["id"]] = r
    return success_obj(report_out(r), 201)


@bp.get("/wte/daily-throughput-reports")
def list_reports():
    require_role(READERS)
    items = sorted(store.throughput_reports.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("status")
    if q is not None:
        items = [r for r in items if r["status"] == q]
    return success_list([report_out(r) for r in items])


@bp.get("/wte/daily-throughput-reports/<rid>")
def get_report(rid):
    require_role(READERS)
    r = store.throughput_reports.get(rid)
    if r is None:
        raise err_not_found("report not found")
    return success_obj(report_out(r))


@bp.put("/wte/daily-throughput-reports/<rid>")
def update_report(rid):
    require_role(PO)
    r = store.throughput_reports.get(rid)
    if r is None:
        raise err_not_found("report not found")
    if r["status"] != "DRAFT":
        raise err_invalid_state("only DRAFT reports may be edited")
    b = body_json()
    if "waste_processed_tonnes" in b:
        r["waste_processed_tonnes"] = to_decimal(b["waste_processed_tonnes"], "waste_processed_tonnes")
    if "avg_heating_value_mj_per_kg" in b:
        r["avg_heating_value_mj_per_kg"] = to_decimal(b["avg_heating_value_mj_per_kg"], "avg_heating_value_mj_per_kg")
    if "operating_hours" in b:
        r["operating_hours"] = to_decimal(b["operating_hours"], "operating_hours")
    _validate_inputs(r["waste_processed_tonnes"], r["avg_heating_value_mj_per_kg"],
                     r["operating_hours"])
    compute_report_fields(r, list(store.boilers.values()))
    touch(r)
    return success_obj(report_out(r))


@bp.post("/wte/daily-throughput-reports/<rid>/finalize")
def finalize_report(rid):
    require_role(PO)
    r = store.throughput_reports.get(rid)
    if r is None:
        raise err_not_found("report not found")
    if r["status"] != "DRAFT":
        raise err_invalid_state("report is not DRAFT")
    if r["capacity_check"] != "OK":
        raise err_422("ERR_CAPACITY_EXCEEDED", "thermal input exceeds effective boiler capacity")
    r["status"] = "FINALIZED"
    touch(r)
    return success_obj(report_out(r))

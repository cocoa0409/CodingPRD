"""FlightHourReport submission (Operator) and verification (FinanceController)."""
from flask import Blueprint

from authz import check_operator_ownership, require_roles
from cascade import apply_report_verification
from envelope import success
from errors import api_err
from routes_admin import get_engine_or_404
from serialize import report_json
from storage import DB, new_id, next_seq, now
from timeutil import check_not_future_period
from validate import as_enum, as_int, as_number, as_period, body, req_field

bp = Blueprint("reports", __name__)

SEVERITY_TIERS = {"BENIGN", "MODERATE", "HARSH"}


@bp.route("/api/engines/<engine_id>/flight-hour-reports", methods=["POST"])
def submit_report(engine_id):
    uid, role = require_roles("Operator")
    engine = get_engine_or_404(engine_id)
    check_operator_ownership(uid, role, engine["operator_id"])
    data = body()
    period_raw = req_field(data, "period")
    period_tuple = as_period(period_raw, "period")
    hours = as_number(req_field(data, "flight_hours"), "flight_hours")
    if hours < 0:
        raise api_err("ERR_INVALID_REQUEST", "flight_hours must be >= 0")
    cycles = as_int(req_field(data, "cycles"), "cycles")
    if cycles < 0:
        raise api_err("ERR_INVALID_REQUEST", "cycles must be >= 0")
    severity = as_enum(req_field(data, "observed_severity"), "observed_severity", SEVERITY_TIERS)
    check_not_future_period(period_tuple, now())
    if any(r["engine_id"] == engine_id and r["period_tuple"] == period_tuple
           for r in DB["reports"].values()):
        raise api_err("ERR_DUPLICATE_REPORT", "a report already exists for this engine and period")
    if engine["agreement_id"] is None:
        raise api_err("ERR_ENGINE_NOT_ENROLLED", "engine is not enrolled in an agreement")
    if engine["status"] != "IN_SERVICE":
        raise api_err("ERR_ENGINE_IN_SHOP", "cannot report while the engine is IN_SHOP")
    ts = now()
    report = {
        "id": new_id(), "engine_id": engine_id, "period": period_raw,
        "period_tuple": period_tuple, "flight_hours": hours, "cycles": cycles,
        "observed_severity": severity, "status": "SUBMITTED", "verified_at": None,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["reports"][report["id"]] = report
    return success(report_json(report), 201)


@bp.route("/api/flight-hour-reports/<report_id>/verify", methods=["POST"])
def verify_report(report_id):
    require_roles("FinanceController")
    report = DB["reports"].get(report_id)
    if report is None:
        raise api_err("ERR_REPORT_NOT_FOUND", "flight-hour report does not exist")
    if report["status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE", "report is not SUBMITTED")
    engine = DB["engines"][report["engine_id"]]
    apply_report_verification(report, engine)
    return success(report_json(report), 200)

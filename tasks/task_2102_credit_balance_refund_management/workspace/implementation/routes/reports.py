"""Audit reporting of credit balance liability (PRD 3.13)."""
from flask import Blueprint, g, request

import auth
import calc
import clock
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("reports", __name__)


@bp.post("/compliance-reports")
@auth.require(auth.COMPLIANCE_OFFICER)
def create_report():
    data = v.body()
    # rank 6 - body shape
    report_type = v.req_enum(data, "report_type", v.REPORT_TYPES)
    scope_code = v.req_str(data, "scope_code")
    period_start_at = v.req_dt(data, "period_start_at")
    period_end_at = v.req_dt(data, "period_end_at")
    as_of_at = v.req_dt(data, "as_of_at")
    # rank 25 - period ordering
    if not (period_start_at < period_end_at and period_end_at <= as_of_at):
        raise ApiError("ERR_INVALID_PERIOD")
    # rank 28 - closed period with a mandatory seven-day separation
    for other in db.compliance_reports.values():
        if other["report_type"] != report_type or other["scope_code"] != scope_code:
            continue
        if other["state"] not in ("DRAFT", "FINALIZED"):
            continue
        after = period_start_at >= clock.add_days(other["period_end_at"],
                                                  calc.REPORT_PERIOD_BUFFER_DAYS)
        before = period_end_at <= clock.add_days(other["period_start_at"],
                                                 -calc.REPORT_PERIOD_BUFFER_DAYS)
        if not (after or before):
            raise ApiError("ERR_REPORT_PERIOD_CONFLICT")

    totals = calc.liability_report(scope_code, as_of_at)
    row = db.base_row()
    row.update({
        "report_type": report_type,
        "scope_code": scope_code,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "as_of_at": as_of_at,
        "generated_by_user_id": g.user_id,
        "state": "DRAFT",
    })
    row.update(totals)
    db.compliance_reports[row["id"]] = row
    return response.ok(derive.compliance_report(row), 201)


@bp.get("/compliance-reports")
@auth.require(*auth.ALL_ROLES)
def list_reports():
    rows = db.ordered(list(db.compliance_reports.values()))
    for name in ("report_type", "state"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return response.page(rows, derive.compliance_report)


@bp.get("/compliance-reports/<report_id>")
@auth.require(*auth.ALL_ROLES)
def read_report(report_id):
    return response.ok(derive.compliance_report(v.must_exist("report", report_id)))


@bp.post("/compliance-reports/<report_id>/finalize")
@auth.require(auth.COMPLIANCE_OFFICER)
def finalize_report(report_id):
    report = v.must_exist("report", report_id)   # rank 3
    if report["state"] != "DRAFT":               # rank 15
        raise ApiError("ERR_REPORT_INVALID_STATE")
    report["state"] = "FINALIZED"
    db.touch(report)
    return response.ok(derive.compliance_report(report))

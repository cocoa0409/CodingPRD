"""National practitioner data bank reporting obligations (PRD 3.9)."""
from flask import Blueprint

import constants as C
from auth import endpoint, npdb_report
from envelope import listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, touch
from val import ZERO, body, d, r2, v_date, v_str

bp = Blueprint("npdb", __name__, url_prefix=C.API_PREFIX)


@bp.get("/npdb-reports/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_report(record_id):
    return ok(npdb_report(record_id))


@bp.get("/npdb-reports")
@endpoint(C.CARRIER_ROLES)
def list_reports():
    limit, offset = pagination()
    records = all_of(db.npdb_reports)
    records = common.eq(records, "claim_id", common.arg("claim_id"))
    records = common.eq(
        records, "settlement_negotiation_id", common.arg("settlement_negotiation_id")
    )
    records = common.eq(records, "insured_id", common.arg("insured_id"))
    records = common.eq(records, "report_status", common.arg("report_status"))
    records = common.boolean(records, "reportable", common.arg("reportable"))
    return listing(records, limit, offset)


@bp.post("/npdb-reports/<record_id>/submission")
@endpoint([C.R_COMPLIANCE])
def submit_report(record_id):
    payload = body()
    submitted_on = v_date(payload, "submitted_on")
    submitter_note = v_str(payload, "submitter_note")

    report = npdb_report(record_id)
    if report["report_status"] != "PENDING":
        raise ApiError("ERR_NPDB_STATE_INVALID")
    if d(submitted_on) < d(report["payment_date"]):
        raise ApiError("ERR_NPDB_SUBMISSION_DATE_INVALID")

    overdue_days = (d(submitted_on) - d(report["due_date"])).days
    report["report_status"] = "SUBMITTED"
    report["submitted_on"] = submitted_on
    report["submitter_note"] = submitter_note
    report["submitted_late"] = overdue_days > 0
    report["days_late"] = overdue_days if overdue_days > 0 else 0
    touch(report)

    insured = db.insureds.get(report["insured_id"])
    if insured is not None:
        insured["npdb_reported_payment_total"] = r2(
            insured["npdb_reported_payment_total"] + report["payment_amount"]
        )
        touch(insured)
    return ok(report)


@bp.post("/npdb-reports/<record_id>/void")
@endpoint([C.R_COMPLIANCE])
def void_report(record_id):
    payload = body()
    void_reason = v_str(payload, "void_reason")

    report = npdb_report(record_id)
    if report["report_status"] != "PENDING":
        raise ApiError("ERR_NPDB_STATE_INVALID")
    report["report_status"] = "VOID"
    report["void_reason"] = void_reason
    touch(report)
    return ok(report)

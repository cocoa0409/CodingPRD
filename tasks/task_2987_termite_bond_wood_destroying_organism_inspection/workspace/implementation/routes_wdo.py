"""Statutory real-estate WDO reports: turnaround, closing lead time, amendments
(PRD 3.4)."""

from datetime import datetime

from flask import Blueprint

import calc
import validate as v
from auth import authenticate
from clock import clock, plus_days, plus_hours
from common import (apply_filters, get_inspection, get_property, get_report,
                    require_graphed, require_purpose)
from envelope import created, listing, ok
from errors import ApiError
from serialize import report_out
from store import by_created, db, new_row, touch

bp = Blueprint("wdo", __name__)

READERS = ("ComplianceOfficer", "BranchManager", "FieldInspector", "PropertyOwner")


@bp.post("/wdo-reports")
def create_report():
    authenticate(("PropertyOwner", "ComplianceOfficer"))
    payload = v.body()
    inspection_id = v.get_string(payload, "inspection_id")
    form_code = v.get_enum(payload, "form_code", calc.FORM_CODES)

    inspection = get_inspection(inspection_id)
    prop = get_property(inspection["property_id"])

    # Stage 15: the snapshotted jurisdiction decides the compliant form.
    state_code = prop["state_code"]
    if form_code != calc.STATE_FORM_MAP[state_code]:
        raise ApiError("ERR_FORM_CODE_MISMATCH", 422,
                       "%s mandates %s, not %s"
                       % (state_code, calc.STATE_FORM_MAP[state_code], form_code))

    requested_at = clock.now()
    row = new_row({
        "inspection_id": inspection["id"],
        "state_code": state_code,
        "form_code": form_code,
        "status": "DRAFT",
        "requested_at": requested_at,
        "due_at": plus_hours(requested_at, calc.STATE_TURNAROUND_HOURS[state_code]),
        "issued_at": None,
        "turnaround_hours": None,
        "sla_breached": False,
        "amendment_count": 0,
        "closing_date": inspection["closing_date"],
        "amendment_reason_code": None,
    })
    db.reports[row["id"]] = row
    return created(report_out(row))


@bp.get("/wdo-reports/<rid>")
def read_report(rid):
    authenticate(READERS)
    return ok(report_out(get_report(rid)))


@bp.get("/wdo-reports")
def list_reports():
    authenticate(READERS)
    rows = apply_filters(by_created(list(db.reports.values())), {
        "inspection_id": v.query_str("inspection_id"),
        "status": v.query_str("status"),
        "sla_breached": v.query_bool("sla_breached"),
    })
    return listing(rows, report_out)


@bp.post("/wdo-reports/<rid>/issue")
def issue_report(rid):
    authenticate(("ComplianceOfficer",))
    report = get_report(rid)

    if report["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_INVALID_REPORT_STATE", 409,
                       "a %s report may not be issued" % report["status"])

    inspection = get_inspection(report["inspection_id"])
    require_graphed(inspection)
    require_purpose(inspection, "REAL_ESTATE")

    now = clock.now()
    closing_date = report["closing_date"]
    if closing_date is not None:
        midnight = datetime(closing_date.year, closing_date.month, closing_date.day)
        deadline = plus_hours(midnight, -calc.CLOSING_LEAD_HOURS)
        if now > deadline:
            raise ApiError("ERR_CLOSING_LEAD_TIME_MISSED", 409,
                           "a report may not be issued inside the final 24 hours "
                           "before closing")

    first_issuance = report["turnaround_hours"] is None
    report["status"] = "ISSUED"
    report["issued_at"] = now
    if first_issuance:
        hours = calc.turnaround_hours(report["requested_at"], now)
        report["turnaround_hours"] = hours
        report["sla_breached"] = hours > calc.STATE_TURNAROUND_HOURS[report["state_code"]]
    touch(report)
    return ok(report_out(report))


@bp.post("/wdo-reports/<rid>/amend")
def amend_report(rid):
    authenticate(("ComplianceOfficer",))
    report = get_report(rid)
    payload = v.body()
    reason = v.get_enum(payload, "amendment_reason_code", calc.AMENDMENT_REASONS)

    if report["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_REPORT_STATE", 409,
                       "only an ISSUED report may be amended")

    last_day = plus_days(report["issued_at"].date(), calc.AMENDMENT_WINDOW_DAYS)
    if clock.today() > last_day:
        raise ApiError("ERR_AMENDMENT_WINDOW_CLOSED", 409,
                       "the 30-day amendment window closed on %s" % last_day)

    report["status"] = "AMENDED"
    report["amendment_count"] = report["amendment_count"] + 1
    report["amendment_reason_code"] = reason
    touch(report)
    return ok(report_out(report))

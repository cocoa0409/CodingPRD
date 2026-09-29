"""Regulatory reporting endpoints (PRD 3.9)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError, bad_request
from utils import D, date_str

bp = Blueprint("reports", __name__)


@bp.post("/regulatory-reports")
def create_report():
    user_id, _role = auth.require([config.ROLE_COMPLIANCE_OFFICER])
    body = validate.json_body()

    field_id = validate.field_id(body, "storage_field_id")
    report_type = validate.field_enum(body, "report_type", config.REPORT_TYPES)
    period_start = validate.field_date(body, "period_start_date")
    period_end = validate.field_date(body, "period_end_date")
    measured = validate.field_number(body, "measured_inventory_dth", exclusive_minimum=0)
    if period_end < period_start:
        raise bad_request("period_end_date must fall on or after period_start_date.")

    field = validate.resolve_body_fk("StorageField", field_id)
    start_text = date_str(period_start)
    end_text = date_str(period_end)

    for existing in store.reports_of_field(field["id"]):
        if (existing["report_type"] == report_type
                and existing["period_start_date"] == start_text
                and existing["period_end_date"] == end_text
                and existing["status"] != "REJECTED"):
            raise ApiError("ERR_DUPLICATE_REPORT_PERIOD",
                           "a live report already covers this field, type and period.")

    book, variance, variance_pct = engine.report_variance(field, measured)
    report = store.new_record()
    report.update({
        "storage_field_id": field["id"],
        "report_type": report_type,
        "period_start_date": start_text,
        "period_end_date": end_text,
        "measured_inventory_dth": measured,
        "book_inventory_dth": book,
        "variance_dth": variance,
        "variance_pct": variance_pct,
        "open_finding_count": engine.open_finding_count(field["id"]),
        "status": "DRAFT",
        "prepared_by_user_id": user_id,
        "submitted_by_user_id": None,
        "agency_outcome": None,
        "agency_response_note": None,
    })
    store.put("RegulatoryReport", report)
    return envelope.created(serialize.report(report))


@bp.post("/regulatory-reports/<report_id>/submit")
def submit_report(report_id):
    user_id, _role = auth.require([config.ROLE_COMPLIANCE_OFFICER])
    validate.json_body(required=False)
    report = validate.resolve_path("RegulatoryReport", report_id)

    if report["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "only a DRAFT or REJECTED report may be submitted.")
    if user_id == report["prepared_by_user_id"]:
        raise ApiError("ERR_SOD_REMEDIATION_SELF_VERIFICATION",
                       "the officer who prepared this filing may not submit it.")
    if D(report["variance_pct"]) > config.MAX_REPORT_VARIANCE_PCT:
        raise ApiError("ERR_REPORT_VARIANCE_EXCEEDED",
                       "the reported variance exceeds the agency tolerance.")

    findings = engine.open_finding_count(report["storage_field_id"])
    if report["report_type"] == "INTEGRITY_PROGRAM_STATUS" and findings != 0:
        raise ApiError("ERR_OPEN_INTEGRITY_FINDINGS",
                       "open integrity work remains on this reservoir.")

    report["open_finding_count"] = findings
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = user_id
    store.touch(report)
    return envelope.object_response(serialize.report(report))


@bp.post("/regulatory-reports/<report_id>/record-agency-response")
def record_agency_response(report_id):
    auth.require([config.ROLE_COMPLIANCE_OFFICER])
    body = validate.json_body()
    outcome = validate.field_enum(body, "agency_outcome", config.AGENCY_OUTCOMES)
    note = validate.field_str(body, "agency_response_note", required=False)
    report = validate.resolve_path("RegulatoryReport", report_id)

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "only a SUBMITTED report may carry an agency disposition.")

    report["status"] = outcome
    report["agency_outcome"] = outcome
    if note is not None:
        report["agency_response_note"] = note
    store.touch(report)
    return envelope.object_response(serialize.report(report))

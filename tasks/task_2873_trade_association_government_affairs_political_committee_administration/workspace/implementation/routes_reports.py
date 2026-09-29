"""Expenditure report endpoints (PRD 3.6)."""
from flask import Blueprint, g

import derive
from constants import API_PREFIX, REPORT_BASES
from core import (
    authenticate, body, clock_date, fail, format_instant, insert, iso_date, now_dt,
    parse_date, respond, touch,
)
from serializers import dump
from validate import get_enum, get_int, get_str

bp = Blueprint("reports", __name__, url_prefix=API_PREFIX)


@bp.post("/expenditure-reports")
def open_report():
    authenticate(["ComplianceOfficer"])
    payload = body()
    registration_id = get_str(payload, "registration_id")
    period_code = get_str(payload, "period_code", max_len=20)
    basis = get_enum(payload, "basis", REPORT_BASES)
    expected_version = get_int(payload, "expected_registration_version")
    registration = derive.lookup("registrations", registration_id, "ERR_REGISTRATION_NOT_FOUND")
    if registration["status"] == "TERMINATED":
        fail("ERR_INVALID_REGISTRATION_STATE",
             "No further report may be opened on a TERMINATED registration.")
    start, end, due, _cadence = derive.require_period(
        period_code, registration["jurisdiction_code"])
    if expected_version != registration["version"]:
        fail("ERR_STALE_REGISTRATION_VERSION",
             "expected_registration_version %s does not match the registration's current "
             "version %s." % (expected_version, registration["version"]))
    for other in derive.where("reports", registration_id=registration_id):
        if other["period_code"] == period_code and other["status"] == "OPEN":
            other["status"] = "SUPERSEDED"
            touch(other)
    report = insert("reports", {
        "registration_id": registration_id,
        "period_code": period_code,
        "period_start_date": iso_date(start),
        "period_end_date": iso_date(end),
        "due_date": iso_date(due),
        "basis": basis,
        "method_a_total_cents": 0,
        "method_b_total_cents": 0,
        "filed_total_cents": 0,
        "included_activity_count": 0,
        "status": "OPEN",
        "created_by_user_id": g.user_id,
        "certified_by_user_id": None,
        "certified_at": None,
        "late": False,
    })
    derive.compute_report_totals(report)
    touch(registration)
    return respond(dump("reports", report), status=201)


@bp.post("/expenditure-reports/<report_id>/certify")
def certify_report(report_id):
    authenticate(["ComplianceOfficer"])
    report = derive.lookup("reports", report_id, "ERR_REPORT_NOT_FOUND")
    if report["status"] != "OPEN":
        fail("ERR_INVALID_REPORT_STATE", "Only an OPEN report can be certified.")
    if report["created_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A report may not be certified by the operator who created it.")
    period_end = parse_date(report["period_end_date"])
    if clock_date() < period_end:
        fail("ERR_PERIOD_NOT_CLOSED", "The reporting period has not closed yet.")
    if report["included_activity_count"] == 0:
        fail("ERR_EMPTY_REPORT", "The report includes no activity.")
    report["status"] = "CERTIFIED"
    report["certified_by_user_id"] = g.user_id
    report["certified_at"] = format_instant(now_dt())
    report["late"] = clock_date() > parse_date(report["due_date"])
    touch(report)
    return respond(dump("reports", report))

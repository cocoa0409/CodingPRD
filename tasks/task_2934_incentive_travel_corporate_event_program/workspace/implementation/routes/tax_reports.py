"""Taxable award reporting (PRD 3.9)."""

from flask import Blueprint

import calc
import serialize
from auth import authorize
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_id, f_int, f_str, raw_fk, validate
from store import db

bp = Blueprint("tax_award_reports", __name__)

READ_ROLES = ("ProgramDirector", "TaxComplianceOfficer")
FILING_STATUSES = ("RECONCILED", "CLOSED")
ANY_EXCEPT_CANCELLED = ("DESIGN", "SOURCING", "CONTRACTED", "REGISTRATION_OPEN",
                        "ONSITE", "RECONCILED", "CLOSED")


@bp.post("/tax-award-reports")
def create_report():
    authorize("TaxComplianceOfficer")
    payload = body()

    qualifier_id = raw_fk(payload, "qualifier_id")
    if qualifier_id is not None:
        lookup("qualifier", qualifier_id)

    data = validate(payload, [
        f_id("qualifier_id"),
        f_int("tax_year", minimum=2000, maximum=2100),
    ])
    qualifier = lookup("qualifier", data["qualifier_id"])
    program = db.programs.get(qualifier["program_id"])
    program_gate(program, ANY_EXCEPT_CANCELLED)

    if qualifier["award_status"] != "TRAVELLED":
        fail("ERR_QUALIFIER_STATE_INVALID")

    if data["tax_year"] != program["fiscal_year"]:
        fail("ERR_PROGRAM_SCOPE_MISMATCH")

    award_value = qualifier["taxable_award_cents"]
    method = program["gross_up_policy"]
    combined_rate_bp, gross_up_cents, reported_value = calc.taxable_award_gross_up(
        award_value, method)

    row = {
        "qualifier_id": qualifier["id"],
        "tax_year": data["tax_year"],
        "award_value_cents": award_value,
        "gross_up_method": method,
        "combined_rate_bp": combined_rate_bp,
        "gross_up_cents": gross_up_cents,
        "reported_value_cents": reported_value,
        "status": "DRAFT",
        "filed_by_user_id": None,
        "filed_at": None,
        "voided_by_user_id": None,
        "void_reason": None,
    }
    db.stamp_new(row)
    db.tax_award_reports[row["id"]] = row

    if qualifier["tax_status"] == "VOIDED":
        qualifier["tax_status"] = "PENDING_REPORT"
        db.touch(qualifier)

    return created(serialize.tax_award_report(row))


@bp.get("/tax-award-reports/<report_id>")
def read_report(report_id):
    authorize(*READ_ROLES)
    return ok(serialize.tax_award_report(lookup("report", report_id)))


@bp.get("/tax-award-reports")
def list_reports():
    authorize(*READ_ROLES)
    rows = filtered(db.ordered(db.tax_award_reports), [
        ("qualifier_id", "qualifier_id"),
        ("tax_year", "tax_year"),
        ("status", "status"),
        ("gross_up_method", "gross_up_method"),
    ])
    return paginate(rows, serialize.tax_award_report)


@bp.post("/tax-award-reports/<report_id>/file")
def file_report(report_id):
    actor = authorize("TaxComplianceOfficer")
    report = lookup("report", report_id)
    body()
    qualifier = db.qualifiers.get(report["qualifier_id"])
    program = db.programs.get(qualifier["program_id"]) if qualifier else None
    program_gate(program, FILING_STATUSES)

    if report["status"] != "DRAFT":
        fail("ERR_TAX_REPORT_STATE_INVALID")
    if qualifier["tax_status"] != "PENDING_REPORT":
        fail("ERR_QUALIFIER_STATE_INVALID")

    report["status"] = "FILED"
    report["filed_by_user_id"] = actor.user_id
    report["filed_at"] = db.logical_now()
    db.touch(report)

    qualifier["tax_status"] = "REPORTED"
    db.touch(qualifier)

    calc.reported_award_total(db, program)
    return ok(serialize.tax_award_report(report))


@bp.post("/tax-award-reports/<report_id>/void")
def void_report(report_id):
    actor = authorize("TaxComplianceOfficer")
    report = lookup("report", report_id)
    data = validate(body(), [f_str("void_reason")])
    qualifier = db.qualifiers.get(report["qualifier_id"])
    program = db.programs.get(qualifier["program_id"]) if qualifier else None
    program_gate(program, FILING_STATUSES)

    if report["status"] != "FILED":
        fail("ERR_TAX_REPORT_STATE_INVALID")
    if actor.user_id == report["filed_by_user_id"]:
        fail("ERR_TAX_VOID_SELF_REVIEW")

    report["status"] = "VOIDED"
    report["voided_by_user_id"] = actor.user_id
    report["void_reason"] = data["void_reason"]
    db.touch(report)

    if qualifier["tax_status"] == "REPORTED":
        qualifier["tax_status"] = "VOIDED"
    db.touch(qualifier)

    calc.reported_award_total(db, program)
    return ok(serialize.tax_award_report(report))

"""Underwriting cases and validation reports."""
from flask import Blueprint

from core import (
    ApiError, db, dump, endpoint, f_enum, f_int, f_str, body, new_row,
    paginate, q_enum, q_str, respond_object, sort_created, touch,
)
from svc import SERVICE_TYPES, finalize_case, maybe_transition_case

bp = Blueprint("underwriting", __name__)

ALL_ROLES = ("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")


@bp.post("/gse/underwriting-cases")
@endpoint("SellerOfficer")
def create_case():
    payload = body()
    loan_id = f_str(payload, "loan_id")
    loan = db.loans.get(loan_id)
    if loan is None:
        raise ApiError("ERR_NOT_FOUND", "Loan not found.")
    if loan["status"] != "DRAFT":
        raise ApiError("ERR_LOAN_NOT_UNDERWRITABLE", "Loan is not in DRAFT status.")
    for existing in db.cases.values():
        if existing["loan_id"] == loan_id and existing["case_status"] != "FINALIZED":
            raise ApiError("ERR_LOAN_NOT_UNDERWRITABLE", "A non-finalized case already exists for this loan.")
    case = new_row(
        "case",
        loan_id=loan_id,
        seller_id=loan["seller_id"],
        submission_round=1,
        case_status="SUBMITTED",
        recommendation="PENDING",
        final_outcome="PENDING",
    )
    db.cases[case["id"]] = case
    return respond_object(dump(case), 201)


def get_case_or_404(case_id):
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_NOT_FOUND", "Underwriting case not found.")
    return case


@bp.get("/gse/underwriting-cases/<case_id>")
@endpoint(*ALL_ROLES)
def get_case(case_id):
    return respond_object(dump(get_case_or_404(case_id)), 200)


@bp.get("/gse/underwriting-cases")
@endpoint(*ALL_ROLES)
def list_cases():
    rows = list(db.cases.values())
    loan_id = q_str("loan_id")
    case_status = q_enum("case_status", ("SUBMITTED", "VALIDATING", "VALIDATED", "FAILED", "FINALIZED"))
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if case_status is not None:
        rows = [r for r in rows if r["case_status"] == case_status]
    return paginate(sort_created(rows))


@bp.post("/gse/underwriting-cases/<case_id>/reports")
@endpoint("Underwriter")
def add_report(case_id):
    case = get_case_or_404(case_id)
    payload = body()
    service_type = f_enum(payload, "service_type", SERVICE_TYPES)
    provider_reference = f_str(payload, "provider_reference")
    if case["case_status"] not in ("SUBMITTED", "VALIDATING", "FAILED"):
        raise ApiError("ERR_INVALID_STATE", "Reports cannot be recorded for a case in status %s." % case["case_status"])
    report = new_row(
        "report",
        audited=False,
        case_id=case["id"],
        round=case["submission_round"],
        service_type=service_type,
        result="PENDING",
        provider_reference=provider_reference,
    )
    db.reports[report["id"]] = report
    if case["case_status"] in ("SUBMITTED", "FAILED"):
        case["case_status"] = "VALIDATING"
        touch(case)
    return respond_object(dump(report), 201)


@bp.get("/gse/validation-reports")
@endpoint(*ALL_ROLES)
def list_reports():
    rows = list(db.reports.values())
    case_id = q_str("case_id")
    service_type = q_enum("service_type", SERVICE_TYPES)
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if service_type is not None:
        rows = [r for r in rows if r["service_type"] == service_type]
    return paginate(sort_created(rows))


@bp.post("/gse/validation-reports/<report_id>/complete")
@endpoint("Underwriter")
def complete_report(report_id):
    report = db.reports.get(report_id)
    if report is None:
        raise ApiError("ERR_NOT_FOUND", "Validation report not found.")
    payload = body()
    result = f_enum(payload, "result", ("VALIDATED", "NOT_VALIDATED"))
    if report["result"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING report can be completed.")
    report["result"] = result
    case = db.cases.get(report["case_id"])
    if case is not None:
        maybe_transition_case(case)
    return respond_object(dump(report), 200)


@bp.post("/gse/underwriting-cases/<case_id>/finalize")
@endpoint("GseUnderwritingEngine")
def finalize(case_id):
    case = get_case_or_404(case_id)
    payload = body()
    expected_case_version = f_int(payload, "expected_case_version")
    if case["case_status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE", "Only a VALIDATED case can be finalized.")
    if int(expected_case_version) != int(case["version"]):
        raise ApiError("ERR_STALE_VERSION", "Case version has advanced since the caller's last read.")
    finalize_case(case)
    return respond_object(dump(case), 200)

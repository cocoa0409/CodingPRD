"""Employer monthly outcomes reports (PRD S3.9)."""
from datetime import datetime

from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_str,
    new_row,
    respond_object,
    touch,
    _MONTH_RE,
)
from core import scope_employer
from domain import compute_report, get_or_404

bp = Blueprint("reports", __name__)


@bp.route("/coe/employers/<emp_id>/reports/generate", methods=["POST"])
@endpoint("ProgramAdmin", "EmployerRep")
def generate_report(emp_id):
    employer = get_or_404("employers", emp_id)
    scope_employer(employer["id"])
    data = body()
    period_month = f_str(data, "period_month")
    if not _MONTH_RE.match(period_month):
        raise ApiError(
            "ERR_MONTH_FORMAT_INVALID", "period_month must be in YYYY-MM form."
        )
    year, month = (int(part) for part in period_month.split("-"))
    if month < 1 or month > 12:
        raise ApiError(
            "ERR_MONTH_FORMAT_INVALID", "period_month must be in YYYY-MM form."
        )

    fields = compute_report(employer["id"], period_month)

    existing = None
    for report in db.reports.values():
        if report["employer_id"] == employer["id"] and report["period_month"] == period_month:
            existing = report
            break
    if existing is None:
        row = new_row(
            "report",
            employer_id=employer["id"],
            period_month=period_month,
            status="GENERATED",
            **fields,
        )
        db.reports[row["id"]] = row
    else:
        row = existing
        for key, value in fields.items():
            row[key] = value
        touch(row)
    return respond_object(dump(row), status=201)


@bp.route("/coe/reports/<report_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep")
def get_report(report_id):
    row = get_or_404("reports", report_id)
    scope_employer(row["employer_id"])
    return respond_object(dump(row))

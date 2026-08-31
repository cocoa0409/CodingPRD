"""Payroll audit program and underpayment recovery (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import serialize
import validate as v
from api_reports import due_date_for
from authz import endpoint, require_owner_employer
from envelope import created, ok
from errors import ApiError
from store import db, month_index, new_row, touch

bp = Blueprint("audits", __name__)

FINDING_FIELDS = ("participant_id", "work_period", "unreported_hours")


def _windows_overlap(a_start, a_end, b_start, b_end):
    return month_index(a_start) <= month_index(b_end) and month_index(b_start) <= month_index(a_end)


@bp.post("/payroll-audits")
@endpoint(["PayrollAuditor"])
def open_audit():
    data = v.body()
    v.body_ref(data, "employer_id", db.employers, "ERR_EMPLOYER_NOT_FOUND")
    v.check_keys(data, ["employer_id", "period_start_month", "period_end_month"])
    employer_id = v.as_string(data, "employer_id")
    start = v.as_month(data, "period_start_month")
    end = v.as_month(data, "period_end_month")
    if month_index(end) < month_index(start):
        v.bad("Field 'period_end_month' may not precede 'period_start_month'.")

    for existing in db.audits.values():
        if existing["employer_id"] != employer_id or existing["status"] == "ABANDONED":
            continue
        if _windows_overlap(start, end, existing["period_start_month"], existing["period_end_month"]):
            raise ApiError("ERR_AUDIT_PERIOD_OVERLAP")

    audit = new_row(
        db.audits,
        {
            "employer_id": employer_id,
            "auditor_user_id": g.user_id,
            "period_start_month": start,
            "period_end_month": end,
            "findings": [],
            "round_count": 1,
            "unreported_hours_found": Decimal("0.00"),
            "underpayment_principal_cents": 0,
            "resulting_report_id": None,
            "status": "IN_FIELDWORK",
        },
    )
    return created(serialize.audit(audit))


@bp.post("/payroll-audits/<audit_id>/findings")
@endpoint(["PayrollAuditor"])
def issue_findings(audit_id):
    audit = v.get_audit(audit_id)
    data = v.body()
    raw = data.get("findings")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                v.body_ref(item, "participant_id", db.participants, "ERR_PARTICIPANT_NOT_FOUND")
    v.check_keys(data, ["findings"])
    if "findings" not in data or data["findings"] is None:
        v.bad("Field 'findings' is required.")
    if not isinstance(data["findings"], list):
        v.bad("Field 'findings' must be an array.")
    findings = []
    for item in data["findings"]:
        if not isinstance(item, dict):
            v.bad("Each entry of 'findings' must be an object.")
        v.check_keys(item, FINDING_FIELDS)
        findings.append(
            {
                "participant_id": v.as_string(item, "participant_id"),
                "work_period": v.as_month(item, "work_period"),
                "unreported_hours": v.as_hours(item, "unreported_hours"),
            }
        )

    if audit["status"] != "IN_FIELDWORK":
        raise ApiError("ERR_AUDIT_INVALID_STATE")
    if g.user_id != audit["auditor_user_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    employer = db.employers[audit["employer_id"]]
    for f in findings:
        participant = db.participants[f["participant_id"]]
        if participant["fund_id"] != employer["fund_id"]:
            raise ApiError("ERR_PARTICIPANT_FUND_MISMATCH")
    for f in findings:
        if not (
            month_index(audit["period_start_month"])
            <= month_index(f["work_period"])
            <= month_index(audit["period_end_month"])
        ):
            v.bad("Every finding's work_period must lie inside the audited window.")

    if not findings:
        audit["findings"] = []
        audit["unreported_hours_found"] = Decimal("0.00")
        audit["underpayment_principal_cents"] = 0
        audit["status"] = "ABANDONED"
    else:
        hours, cents = calc.audit_underpayment(
            findings, employer["contribution_rate_millicents_per_hour"]
        )
        audit["findings"] = findings
        audit["unreported_hours_found"] = hours
        audit["underpayment_principal_cents"] = cents
        audit["status"] = "FINDINGS_ISSUED"
    touch(audit)
    return ok(serialize.audit(audit))


@bp.post("/payroll-audits/<audit_id>/respond")
@endpoint(["ContributingEmployer"])
def respond_to_findings(audit_id):
    audit = db.audits.get(audit_id)
    if audit is not None:
        require_owner_employer(audit["employer_id"])
    audit = v.get_audit(audit_id)
    data = v.body()
    v.check_keys(data, ["response", "dispute_note"])
    response = v.as_enum(data, "response", ("ACCEPT", "DISPUTE"))
    v.as_string(data, "dispute_note", required=False, default=None)

    if audit["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_INVALID_STATE")
    if response == "DISPUTE" and audit["round_count"] >= calc.MAX_AUDIT_ROUNDS:
        raise ApiError("ERR_AUDIT_ROUND_LIMIT_REACHED")

    if response == "ACCEPT":
        audit["status"] = "EMPLOYER_ACCEPTED"
    else:
        audit["status"] = "IN_FIELDWORK"
        audit["round_count"] = audit["round_count"] + 1
        audit["findings"] = []
        audit["unreported_hours_found"] = Decimal("0.00")
        audit["underpayment_principal_cents"] = 0
    touch(audit)
    return ok(serialize.audit(audit))


@bp.post("/payroll-audits/<audit_id>/finalize")
@endpoint(["FundAdministrator"])
def finalize_audit(audit_id):
    audit = v.get_audit(audit_id)
    v.check_keys(v.body(), [])
    employer = db.employers[audit["employer_id"]]

    if audit["status"] != "EMPLOYER_ACCEPTED":
        raise ApiError("ERR_AUDIT_INVALID_STATE")

    approved = any(
        m["fund_id"] == employer["fund_id"]
        and m["subject_type"] == "AUDIT_SETTLEMENT"
        and m["subject_ref_id"] == audit["id"]
        and m["status"] in ("CARRIED", "ARBITRATION_CARRIED")
        for m in db.motions.values()
    )
    if not approved:
        raise ApiError("ERR_BOARD_APPROVAL_REQUIRED")
    if g.user_id == audit["auditor_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    work_period = audit["period_end_month"]
    report = new_row(
        db.reports,
        {
            "employer_id": employer["id"],
            "work_period": work_period,
            "amends_report_id": None,
            "origin": "AUDIT",
            "due_date": due_date_for(work_period),
            "total_hours_reported": Decimal("0.00"),
            "total_contributions_due_cents": 0,
            "amount_remitted_cents": 0,
            "filing_status": "POSTED",
            "payment_status": "UNPAID",
            "posted_at": db.now,
            "paid_in_full_at": None,
        },
    )
    for f in audit["findings"]:
        new_row(
            db.lines,
            {
                "report_id": report["id"],
                "participant_id": f["participant_id"],
                "hours": f["unreported_hours"],
                "gross_wages_cents": 0,
                "work_classification": "JOURNEYMAN",
                "contribution_cents": 0,
            },
            common=False,
        )
    calc.recompute_report_totals(report)

    audit["resulting_report_id"] = report["id"]
    audit["status"] = "CLOSED"
    touch(audit)

    affected = []
    for f in audit["findings"]:
        if f["participant_id"] not in affected:
            affected.append(f["participant_id"])
    for pid in affected:
        calc.cascade_participant(db.participants[pid])

    calc.ledger_cascade(employer)
    return ok(serialize.audit(audit))

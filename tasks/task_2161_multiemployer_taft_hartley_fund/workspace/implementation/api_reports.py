"""Contribution report intake, remittance, posting and delinquency charges."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import serialize
import validate as v
from authz import endpoint, require_owner_employer
from envelope import created, ok
from errors import ApiError
from store import date_from_iso, db, month_add, new_row, touch

bp = Blueprint("reports", __name__)

LINE_FIELDS = ("participant_id", "hours", "gross_wages_cents", "work_classification")
WORK_CLASSES = ("JOURNEYMAN", "APPRENTICE", "FOREMAN")


def due_date_for(work_period):
    return month_add(work_period, 1) + "-20"


def _validate_lines(data):
    if "lines" not in data or data["lines"] is None:
        v.bad("Field 'lines' is required.")
    raw = data["lines"]
    if not isinstance(raw, list):
        v.bad("Field 'lines' must be an array.")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            v.bad("Each entry of 'lines' must be an object.")
        v.check_keys(item, LINE_FIELDS)
        out.append(
            {
                "participant_id": v.as_string(item, "participant_id"),
                "hours": v.as_hours(item, "hours"),
                "gross_wages_cents": v.as_int(item, "gross_wages_cents", minimum=0),
                "work_classification": v.as_enum(item, "work_classification", WORK_CLASSES),
            }
        )
    return out


def live_report_for_period(employer_id, work_period):
    for r in db.reports.values():
        if (
            r["employer_id"] == employer_id
            and r["work_period"] == work_period
            and r["filing_status"] != "SUPERSEDED"
        ):
            return r
    return None


def amendment_target_valid(target, employer_id, work_period):
    return (
        target is not None
        and target["filing_status"] == "POSTED"
        and target["employer_id"] == employer_id
        and target["work_period"] == work_period
    )


REPORT_FIELDS = ["employer_id", "work_period", "lines", "expected_employer_version", "amends_report_id"]


@bp.post("/contribution-reports")
@endpoint(["ContributingEmployer", "FundAdministrator"])
def file_report():
    data = v.body()
    # ladder step 3 - ownership on the body's employer_id
    if g.role == "ContributingEmployer":
        candidate = data.get("employer_id")
        if isinstance(candidate, str) and candidate != g.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # ladder step 5 - body reference existence
    v.body_ref(data, "employer_id", db.employers, "ERR_EMPLOYER_NOT_FOUND")
    v.body_ref(data, "amends_report_id", db.reports, "ERR_REPORT_NOT_FOUND")
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if isinstance(item, dict):
                v.body_ref(item, "participant_id", db.participants, "ERR_PARTICIPANT_NOT_FOUND")

    # ladder step 6 - request shape
    v.check_keys(data, REPORT_FIELDS)
    employer_id = v.as_string(data, "employer_id")
    work_period = v.as_month(data, "work_period")
    expected_version = v.as_int(data, "expected_employer_version", minimum=0)
    amends_report_id = v.as_string(data, "amends_report_id", required=False, default=None)
    lines = _validate_lines(data)

    employer = db.employers[employer_id]

    # ladder step 7 - stale parent version
    if expected_version != employer["version"]:
        raise ApiError("ERR_STALE_EMPLOYER_VERSION")

    # ladder step 10 - governance safety
    if employer["status"] == "WITHDRAWN":
        raise ApiError("ERR_EMPLOYER_WITHDRAWN")

    # ladder step 12 - cross-entity linkage
    for entry in lines:
        participant = db.participants[entry["participant_id"]]
        if participant["fund_id"] != employer["fund_id"]:
            raise ApiError("ERR_PARTICIPANT_FUND_MISMATCH")

    # ladder step 13 - uniqueness and chain rules
    if not lines:
        raise ApiError("ERR_EMPTY_REPORT")
    if amends_report_id is None:
        if live_report_for_period(employer_id, work_period) is not None:
            raise ApiError("ERR_DUPLICATE_WORK_PERIOD")
    else:
        target = db.reports.get(amends_report_id)
        if not amendment_target_valid(target, employer_id, work_period):
            raise ApiError("ERR_AMENDMENT_TARGET_INVALID")

    report = new_row(
        db.reports,
        {
            "employer_id": employer_id,
            "work_period": work_period,
            "amends_report_id": amends_report_id,
            "origin": "EMPLOYER",
            "due_date": due_date_for(work_period),
            "total_hours_reported": Decimal("0.00"),
            "total_contributions_due_cents": 0,
            "amount_remitted_cents": 0,
            "filing_status": "SUBMITTED",
            "payment_status": "UNPAID",
            "posted_at": None,
            "paid_in_full_at": None,
        },
    )
    for entry in lines:
        new_row(
            db.lines,
            {
                "report_id": report["id"],
                "participant_id": entry["participant_id"],
                "hours": entry["hours"],
                "gross_wages_cents": entry["gross_wages_cents"],
                "work_classification": entry["work_classification"],
                "contribution_cents": 0,
            },
            common=False,
        )
    calc.recompute_report_totals(report)
    calc.recompute_employer_ledger(employer)
    touch(employer)
    return created(serialize.report(report))


@bp.post("/contribution-reports/<report_id>/remit")
@endpoint(["ContributingEmployer", "FundAdministrator"])
def remit(report_id):
    report = db.reports.get(report_id)
    if report is not None:
        require_owner_employer(report["employer_id"])
    report = v.get_report(report_id)
    data = v.body()
    v.check_keys(data, ["amount_cents"])
    amount = v.as_int(data, "amount_cents", minimum=0)

    if report["filing_status"] == "SUPERSEDED":
        raise ApiError("ERR_REPORT_NOT_REMITTABLE")
    balance = report["total_contributions_due_cents"] - report["amount_remitted_cents"]
    if amount > balance:
        raise ApiError("ERR_REMITTANCE_EXCEEDS_BALANCE")

    if amount == balance:
        report["amount_remitted_cents"] = report["total_contributions_due_cents"]
        report["paid_in_full_at"] = db.now
        report["payment_status"] = "PAID_IN_FULL"
    else:
        report["amount_remitted_cents"] = report["amount_remitted_cents"] + amount
        if amount > 0:
            report["payment_status"] = "PARTIAL"
    touch(report)
    calc.ledger_cascade(db.employers[report["employer_id"]])
    return ok(serialize.report(report))


@bp.post("/contribution-reports/<report_id>/post")
@endpoint(["FundAdministrator"])
def post_report(report_id):
    report = v.get_report(report_id)
    v.check_keys(v.body(), [])
    employer = db.employers[report["employer_id"]]

    if report["filing_status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_ALREADY_POSTED")
    if employer["status"] == "WITHDRAWN":
        raise ApiError("ERR_EMPLOYER_WITHDRAWN")
    lines = calc.report_lines(report["id"])
    if not lines:
        raise ApiError("ERR_EMPTY_REPORT")
    target = None
    if report["amends_report_id"] is not None:
        target = db.reports.get(report["amends_report_id"])
        if not amendment_target_valid(target, report["employer_id"], report["work_period"]):
            raise ApiError("ERR_AMENDMENT_TARGET_INVALID")

    affected = set(l["participant_id"] for l in lines)

    calc.recompute_report_totals(report)
    report["posted_at"] = db.now
    report["filing_status"] = "POSTED"
    touch(report)

    if target is not None:
        target["filing_status"] = "SUPERSEDED"
        touch(target)
        for l in calc.report_lines(target["id"]):
            affected.add(l["participant_id"])

    for pid in sorted(affected, key=lambda i: (db.participants[i]["created_at"], db.participants[i]["_seq"])):
        calc.cascade_participant(db.participants[pid])

    calc.ledger_cascade(employer)
    return ok(serialize.report(report))


@bp.post("/contribution-reports/<report_id>/delinquency-assessments")
@endpoint(["FundAdministrator"])
def raise_assessment(report_id):
    report = v.get_report(report_id)
    data = v.body()
    v.check_keys(data, ["basis"])
    basis = v.as_enum(data, "basis", ("STATUTORY", "PLAN_SCHEDULE"))

    if report["filing_status"] == "SUPERSEDED":
        raise ApiError("ERR_REPORT_ALREADY_POSTED")

    employer = db.employers[report["employer_id"]]
    fund = db.funds[employer["fund_id"]]
    assessed_on = db.today
    days_late = (assessed_on - date_from_iso(report["due_date"])).days
    if days_late < 0:
        days_late = 0
    if days_late <= 0:
        raise ApiError("ERR_REPORT_NOT_DELINQUENT")

    principal = report["total_contributions_due_cents"] - report["amount_remitted_cents"]
    if principal <= 0:
        raise ApiError("ERR_NO_DELINQUENT_PRINCIPAL")

    interest, ld = calc.delinquency_charges(basis, principal, days_late, fund)
    assessment = new_row(
        db.assessments,
        {
            "report_id": report["id"],
            "basis": basis,
            "assessed_on": assessed_on.isoformat(),
            "days_late": days_late,
            "principal_cents": principal,
            "interest_cents": interest,
            "liquidated_damages_cents": ld,
            "total_cents": principal + interest + ld,
            "status": "ASSESSED",
            "settlement_amount_cents": None,
            "waived_cents": None,
        },
    )
    calc.recompute_employer_ledger(employer)
    touch(employer)
    return created(serialize.assessment(assessment))


@bp.post("/delinquency-assessments/<assessment_id>/settle")
@endpoint(["FundAdministrator"])
def settle_assessment(assessment_id):
    assessment = v.get_assessment(assessment_id)
    data = v.body()
    v.check_keys(data, ["settlement_amount_cents"])
    amount = v.as_int(data, "settlement_amount_cents", minimum=0)

    if assessment["status"] != "ASSESSED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    if amount > assessment["total_cents"]:
        raise ApiError("ERR_SETTLEMENT_EXCEEDS_ASSESSMENT")

    assessment["settlement_amount_cents"] = amount
    assessment["status"] = "SETTLED"
    touch(assessment)

    report = db.reports[assessment["report_id"]]
    calc.ledger_cascade(db.employers[report["employer_id"]])
    return ok(serialize.assessment(assessment))

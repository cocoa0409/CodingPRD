"""All GET endpoints."""
from flask import Blueprint, request

import calc
import serialize
import validate as v
from authz import endpoint
from envelope import ok, paginate
from store import db, sorted_rows

bp = Blueprint("reads", __name__)

ALL = ["FundAdministrator", "ContributingEmployer", "Trustee", "PayrollAuditor", "Actuary"]
NO_EMPLOYER = ["FundAdministrator", "Trustee", "PayrollAuditor", "Actuary"]
ASSESSMENT_READERS = ["FundAdministrator", "ContributingEmployer", "Trustee"]
AUDIT_READERS = ["FundAdministrator", "ContributingEmployer", "Trustee", "PayrollAuditor"]
WITHDRAWAL_READERS = ["FundAdministrator", "ContributingEmployer", "Trustee", "Actuary"]
BOARD_READERS = ["FundAdministrator", "Trustee"]

_MISS = object()


def _filter(rows, key, param=None, cast=None):
    param = param or key
    raw = request.args.get(param)
    if raw is None:
        return rows
    if cast is not None:
        try:
            wanted = cast(raw)
        except (TypeError, ValueError):
            return []
    else:
        wanted = raw
    return [r for r in rows if r.get(key, _MISS) == wanted]


# --------------------------------------------------------------------- funds
@bp.get("/funds/<fund_id>")
@endpoint(ALL)
def read_fund(fund_id):
    return ok(serialize.fund(v.get_fund(fund_id)))


@bp.get("/funds/<fund_id>/trustees")
@endpoint(ALL)
def list_fund_trustees(fund_id):
    fund = v.get_fund(fund_id)
    rows = [t for t in db.trustees.values() if t["fund_id"] == fund["id"]]
    rows = _filter(rows, "seat_status")
    rows = _filter(rows, "appointing_party")
    return paginate(sorted_rows(rows), serialize.trustee)


# ----------------------------------------------------------------- employers
@bp.get("/employers/<employer_id>")
@endpoint(ALL)
def read_employer(employer_id):
    return ok(serialize.employer(v.get_employer(employer_id)))


@bp.get("/employers")
@endpoint(NO_EMPLOYER)
def list_employers():
    rows = list(db.employers.values())
    rows = _filter(rows, "fund_id")
    rows = _filter(rows, "controlled_group_parent_employer_id")
    rows = _filter(rows, "status")
    return paginate(sorted_rows(rows), serialize.employer)


# -------------------------------------------------------------- participants
@bp.get("/participants/<participant_id>")
@endpoint(ALL)
def read_participant(participant_id):
    return ok(serialize.participant(v.get_participant(participant_id)))


@bp.get("/participants")
@endpoint(NO_EMPLOYER)
def list_participants():
    rows = list(db.participants.values())
    rows = _filter(rows, "fund_id")
    rows = _filter(rows, "status")
    wanted = request.args.get("eligibility_status")
    if wanted is not None:
        rows = [r for r in rows if calc.eligibility_status(r) == wanted]
    return paginate(sorted_rows(rows), serialize.participant)


@bp.get("/participants/<participant_id>/pension-accruals")
@endpoint(ALL)
def list_pension_accruals(participant_id):
    participant = v.get_participant(participant_id)
    rows = [a for a in db.accruals.values() if a["participant_id"] == participant["id"]]
    rows = _filter(rows, "plan_year", cast=int)
    rows = _filter(rows, "accrual_status")
    rows.sort(key=lambda a: (a["plan_year"], a["_seq"]))
    return paginate(rows, serialize.accrual)


@bp.get("/participants/<participant_id>/contribution-lines")
@endpoint(ALL)
def list_participant_lines(participant_id):
    participant = v.get_participant(participant_id)
    rows = [l for l in db.lines.values() if l["participant_id"] == participant["id"]]
    rows = _filter(rows, "report_id")
    return paginate(sorted_rows(rows), serialize.line)


# ----------------------------------------------------------- coverage months
@bp.get("/coverage-months/<coverage_month_id>")
@endpoint(ALL)
def read_coverage_month(coverage_month_id):
    return ok(serialize.coverage_month(v.get_coverage_month(coverage_month_id)))


@bp.get("/coverage-months")
@endpoint(ALL)
def list_coverage_months():
    rows = list(db.coverage_months.values())
    rows = _filter(rows, "participant_id")
    rows = _filter(rows, "granting_report_id")
    rows = _filter(rows, "status")
    rows = _filter(rows, "coverage_month")
    rows = _filter(rows, "source")
    return paginate(sorted_rows(rows), serialize.coverage_month)


# ------------------------------------------------------ contribution reports
@bp.get("/contribution-reports/<report_id>")
@endpoint(ALL)
def read_report(report_id):
    return ok(serialize.report(v.get_report(report_id)))


@bp.get("/contribution-reports")
@endpoint(ALL)
def list_reports():
    rows = list(db.reports.values())
    rows = _filter(rows, "employer_id")
    rows = _filter(rows, "amends_report_id")
    rows = _filter(rows, "filing_status")
    rows = _filter(rows, "payment_status")
    rows = _filter(rows, "work_period")
    rows = _filter(rows, "origin")
    return paginate(sorted_rows(rows), serialize.report)


@bp.get("/contribution-reports/<report_id>/lines")
@endpoint(ALL)
def list_report_lines(report_id):
    report = v.get_report(report_id)
    rows = [l for l in db.lines.values() if l["report_id"] == report["id"]]
    return paginate(sorted_rows(rows), serialize.line)


@bp.get("/contribution-reports/<report_id>/delinquency-assessments")
@endpoint(ASSESSMENT_READERS)
def list_report_assessments(report_id):
    report = v.get_report(report_id)
    rows = [a for a in db.assessments.values() if a["report_id"] == report["id"]]
    rows = _filter(rows, "status")
    rows = _filter(rows, "basis")
    return paginate(sorted_rows(rows), serialize.assessment)


# --------------------------------------------------------------- audits
@bp.get("/payroll-audits/<audit_id>")
@endpoint(AUDIT_READERS)
def read_audit(audit_id):
    return ok(serialize.audit(v.get_audit(audit_id)))


@bp.get("/payroll-audits")
@endpoint(AUDIT_READERS)
def list_audits():
    rows = list(db.audits.values())
    rows = _filter(rows, "employer_id")
    rows = _filter(rows, "status")
    rows = _filter(rows, "resulting_report_id")
    return paginate(sorted_rows(rows), serialize.audit)


# --------------------------------------------------- withdrawal assessments
@bp.get("/withdrawal-assessments/<assessment_id>")
@endpoint(WITHDRAWAL_READERS)
def read_withdrawal(assessment_id):
    return ok(serialize.withdrawal(v.get_withdrawal(assessment_id)))


@bp.get("/withdrawal-assessments")
@endpoint(WITHDRAWAL_READERS)
def list_withdrawals():
    rows = list(db.withdrawals.values())
    rows = _filter(rows, "employer_id")
    rows = _filter(rows, "status")
    rows = _filter(rows, "method")
    return paginate(sorted_rows(rows), serialize.withdrawal)


@bp.get("/withdrawal-assessments/<assessment_id>/installments")
@endpoint(WITHDRAWAL_READERS)
def list_installments(assessment_id):
    assessment = v.get_withdrawal(assessment_id)
    rows = [i for i in db.installments.values() if i["assessment_id"] == assessment["id"]]
    rows = _filter(rows, "status")
    rows.sort(key=lambda i: (i["installment_number"], i["_seq"]))
    return paginate(rows, serialize.installment)


# --------------------------------------------------------- board governance
@bp.get("/board-motions/<motion_id>")
@endpoint(ALL)
def read_motion(motion_id):
    return ok(serialize.motion(v.get_motion(motion_id)))


@bp.get("/board-motions")
@endpoint(ALL)
def list_motions():
    rows = list(db.motions.values())
    rows = _filter(rows, "fund_id")
    rows = _filter(rows, "status")
    rows = _filter(rows, "subject_type")
    rows = _filter(rows, "subject_ref_id")
    rows = _filter(rows, "moved_by_trustee_id")
    return paginate(sorted_rows(rows), serialize.motion)


@bp.get("/motion-votes/<vote_id>")
@endpoint(BOARD_READERS)
def read_vote(vote_id):
    return ok(serialize.vote(v.get_vote(vote_id)))


@bp.get("/motion-votes")
@endpoint(BOARD_READERS)
def list_votes():
    rows = list(db.votes.values())
    rows = _filter(rows, "motion_id")
    rows = _filter(rows, "trustee_id")
    rows = _filter(rows, "position")
    return paginate(sorted_rows(rows), serialize.vote)


# ------------------------------------------------------ reciprocity transfers
@bp.get("/reciprocity-transfers/<transfer_id>")
@endpoint(BOARD_READERS)
def read_transfer(transfer_id):
    return ok(serialize.transfer(v.get_transfer(transfer_id)))


@bp.get("/reciprocity-transfers")
@endpoint(BOARD_READERS)
def list_transfers():
    rows = list(db.transfers.values())
    rows = _filter(rows, "participant_id")
    rows = _filter(rows, "sister_fund_id")
    rows = _filter(rows, "status")
    rows = _filter(rows, "transfer_type")
    return paginate(sorted_rows(rows), serialize.transfer)

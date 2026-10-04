"""FindingsReport endpoints: create, list, submit, review, agency-decision,
publish."""
from datetime import timedelta

from flask import Blueprint

import store
from calc import PEER_REVIEW_DAYS, PUBLICATION_DAYS, REVISION_DAYS
from clock import now_dt
from errors import raise_err
from serialize import report_out
from services import (latest_preregistered_plan, maybe_complete_study,
                      reports_of_study)
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_AGENCY_OFFICER, ROLE_PEER_REVIEWER,
                        ROLE_PRINCIPAL_INVESTIGATOR, STAFF_ROLES,
                        authenticate, authorize, check_schema, get_json_body)

bp = Blueprint("reports", __name__)


def get_report_or_404(report_id):
    report = store.reports.get(report_id)
    if report is None:
        raise_err("ERR_NOT_FOUND", "Report not found")
    return report


@bp.post("/evaluation/studies/<study_id>/reports")
def create_report(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "title": ("str", True),
        "report_type": ("enum:INTERIM|FINAL", True),
        "addressed_primary_outcomes": ("arr_str", True),
        "payment_milestone_cents": ("int", True),
    })
    if body["payment_milestone_cents"] < 0:
        raise_err("ERR_INVALID_REQUEST",
                  "payment_milestone_cents must be >= 0")
    if study["status"] not in ("ANALYSIS", "REPORTING", "DISSEMINATION"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "Reports may only be drafted while the study is in "
                  "ANALYSIS, REPORTING, or DISSEMINATION")
    report = new_entity({
        "study_id": study_id,
        "title": body["title"],
        "report_type": body["report_type"],
        "addressed_primary_outcomes": body["addressed_primary_outcomes"],
        "payment_milestone_cents": body["payment_milestone_cents"],
        "revision_count": 0,
        "submitted_by_id": None,
        "reviewed_by_id": None,
        "submitted_at": None,
        "accepted_at": None,
        "peer_review_due": None,
        "revision_due": None,
        "publication_due": None,
        "status": "DRAFT",
    })
    store.reports[report["id"]] = report
    if study["status"] == "ANALYSIS":
        study["status"] = "REPORTING"
        touch(study)
    return ok_obj(report_out(report), 201)


@bp.get("/evaluation/studies/<study_id>/reports")
def list_reports(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(reports_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([report_out(r) for r in page], limit, offset, total)


@bp.post("/evaluation/reports/<report_id>/submit")
def submit_report(report_id):
    uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    report = get_report_or_404(report_id)
    body = get_json_body()
    check_schema(body, {})
    if report["status"] not in ("DRAFT", "REVISION"):
        raise_err("ERR_REPORT_INVALID_STATE",
                  "Only a DRAFT or REVISION report can be submitted")
    aplan = latest_preregistered_plan(report["study_id"])
    if aplan is None:
        raise_err("ERR_ANALYSIS_PLAN_NOT_REGISTERED",
                  "The study must hold a PREREGISTERED analysis plan")
    now = now_dt()
    if (report["status"] == "REVISION"
            and report["revision_due"] is not None
            and now > report["revision_due"]):
        raise_err("ERR_REVISION_DEADLINE_MISSED",
                  "Resubmission is past the revision deadline")
    missing = [c for c in aplan["primary_outcomes"]
               if c not in report["addressed_primary_outcomes"]]
    if missing:
        raise_err("ERR_UNREPORTED_PRIMARY_OUTCOME",
                  "Report does not address every preregistered primary "
                  "outcome")
    report["submitted_at"] = now
    report["submitted_by_id"] = uid
    report["peer_review_due"] = now + timedelta(days=PEER_REVIEW_DAYS)
    report["revision_due"] = None
    report["status"] = "SUBMITTED"
    touch(report)
    return ok_obj(report_out(report))


@bp.post("/evaluation/reports/<report_id>/review")
def review_report(report_id):
    uid, role = authenticate()
    authorize(role, [ROLE_PEER_REVIEWER])
    report = get_report_or_404(report_id)
    body = get_json_body()
    check_schema(body, {"reviewer_notes": ("str", False)})
    if report["status"] != "SUBMITTED":
        raise_err("ERR_REPORT_INVALID_STATE",
                  "Only a SUBMITTED report can be peer reviewed")
    if uid == report["submitted_by_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The reviewer must differ from the submitter")
    report["reviewed_by_id"] = uid
    report["status"] = "PEER_REVIEWED"
    touch(report)
    return ok_obj(report_out(report))


@bp.post("/evaluation/reports/<report_id>/agency-decision")
def report_agency_decision(report_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    report = get_report_or_404(report_id)
    body = get_json_body()
    check_schema(body, {
        "decision": ("enum:ACCEPTED|REVISION_REQUIRED", True),
    })
    if report["status"] != "PEER_REVIEWED":
        raise_err("ERR_REPORT_INVALID_STATE",
                  "Only a PEER_REVIEWED report can receive an agency "
                  "decision")
    now = now_dt()
    if body["decision"] == "ACCEPTED":
        report["accepted_at"] = now
        report["publication_due"] = now + timedelta(days=PUBLICATION_DAYS)
        report["status"] = "ACCEPTED"
    else:
        report["revision_count"] += 1
        report["revision_due"] = now + timedelta(days=REVISION_DAYS)
        report["status"] = "REVISION"
    touch(report)
    return ok_obj(report_out(report))


@bp.post("/evaluation/reports/<report_id>/publish")
def publish_report(report_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    report = get_report_or_404(report_id)
    body = get_json_body()
    check_schema(body, {})
    if report["status"] != "ACCEPTED":
        raise_err("ERR_REPORT_INVALID_STATE",
                  "Only an ACCEPTED report can be published")
    now = now_dt()
    if (report["publication_due"] is not None
            and now > report["publication_due"]):
        raise_err("ERR_PUBLICATION_DEADLINE_MISSED",
                  "Publication is past the publication deadline")
    study = store.studies.get(report["study_id"])
    contract = store.contracts.get(study["contract_id"])
    if report["payment_milestone_cents"] > contract["remaining_cents"]:
        raise_err("ERR_INSUFFICIENT_CONTRACT_FUNDS",
                  "Payment milestone exceeds the contract's remaining funds")
    contract["disbursed_cents"] += report["payment_milestone_cents"]
    contract["remaining_cents"] = (contract["award_amount_cents"]
                                   - contract["disbursed_cents"]
                                   - contract["forfeited_cents"])
    touch(contract)
    report["status"] = "PUBLISHED"
    touch(report)
    if study["status"] == "REPORTING":
        study["status"] = "DISSEMINATION"
        touch(study)
    maybe_complete_study(study)
    return ok_obj(report_out(report))

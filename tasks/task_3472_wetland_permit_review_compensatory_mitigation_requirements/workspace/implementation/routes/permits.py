"""Permit and MonitoringReport endpoints (PRD §3.7, §3.8)."""

from flask import Blueprint

import calculations as calc
from db import STORE, bump, get_clock
from errors import api_err
from helpers import get_body, opt_str, req_datetime, req_enum, req_str
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import permit_out, report_out

bp = Blueprint("permits", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")


def _get_permit_or_404(permit_id):
    permit = STORE["permits"].get(permit_id)
    if permit is None:
        raise api_err("ERR_PERMIT_NOT_FOUND", "No Permit with id %s" % permit_id)
    return permit


def _permit_owner_applicant_id(permit):
    app = STORE["applications"].get(permit["application_id"])
    return app["applicant_id"] if app else None


@bp.get("/wetland-permits/permits")
def list_permits():
    require_roles(list(ALL_ROLES))
    permits = apply_filters(STORE["permits"].values(), {
        "application_id": "application_id",
        "status": "status",
    })
    return list_response(permits, permit_out)


@bp.get("/wetland-permits/permits/<id>")
def get_permit(id):
    require_roles(list(ALL_ROLES))
    return success_obj(permit_out(_get_permit_or_404(id)))


@bp.post("/wetland-permits/permits/<id>/commence-work")
def commence_work(id):
    user_id, role = require_roles(["Applicant"])
    permit = _get_permit_or_404(id)
    check_ownership(user_id, role, _permit_owner_applicant_id(permit))
    get_body()
    if permit["status"] != "ISSUED":
        raise api_err("ERR_PERMIT_INVALID_STATE",
                      "commence-work requires an ISSUED permit")
    permit["status"] = "ACTIVE"
    bump(permit)
    return success_obj(permit_out(permit))


@bp.post("/wetland-permits/permits/<id>/reinstate")
def reinstate_permit(id):
    require_roles(["DistrictEngineer"])
    permit = _get_permit_or_404(id)
    get_body()
    if permit["status"] != "SUSPENDED":
        raise api_err("ERR_PERMIT_INVALID_STATE",
                      "reinstate requires a SUSPENDED permit")
    # Priority 30: no OVERDUE report of this permit may remain.
    for report in STORE["reports"].values():
        if report["permit_id"] == permit["id"] \
                and report["status"] == "OVERDUE":
            raise api_err("ERR_REPORTS_OVERDUE_EXIST",
                          "The permit still has OVERDUE monitoring reports")
    permit["status"] = "ACTIVE"
    bump(permit)
    return success_obj(permit_out(permit))


@bp.post("/wetland-permits/permits/<id>/close")
def close_permit(id):
    require_roles(["DistrictEngineer"])
    permit = _get_permit_or_404(id)
    get_body()
    if permit["status"] != "ACTIVE":
        raise api_err("ERR_PERMIT_INVALID_STATE",
                      "close requires an ACTIVE permit")
    # Priority 30: all five reports ACCEPTED and the plan COMPLETED.
    reports = [r for r in STORE["reports"].values()
               if r["permit_id"] == permit["id"]]
    all_accepted = len(reports) >= calc.MONITORING_REPORT_COUNT and all(
        r["status"] == "ACCEPTED" for r in reports)
    plan = None
    if reports:
        plan = STORE["plans"].get(reports[0]["plan_id"])
    if plan is None:
        plan = next((p for p in STORE["plans"].values()
                     if p["application_id"] == permit["application_id"]
                     and p["status"] == "COMPLETED"), None)
    if not all_accepted or plan is None or plan["status"] != "COMPLETED":
        raise api_err("ERR_MONITORING_INCOMPLETE",
                      "Permit close requires five ACCEPTED monitoring "
                      "reports and a COMPLETED mitigation plan")
    permit["status"] = "CLOSED"
    bump(permit)
    return success_obj(permit_out(permit))


# ---------------------------------------------------------------------------
# Monitoring reports
# ---------------------------------------------------------------------------

def _get_report_or_404(report_id):
    report = STORE["reports"].get(report_id)
    if report is None:
        raise api_err("ERR_REPORT_NOT_FOUND",
                      "No MonitoringReport with id %s" % report_id)
    return report


@bp.get("/wetland-permits/monitoring-reports")
def list_reports():
    require_roles(list(ALL_ROLES))
    reports = apply_filters(STORE["reports"].values(), {
        "permit_id": "permit_id",
        "plan_id": "plan_id",
        "status": "status",
    })
    # The one pinned non-default sort: period_index ascending.
    return list_response(
        reports, report_out,
        sort=lambda r: (r["period_index"], r["created_seq"]))


@bp.get("/wetland-permits/monitoring-reports/<id>")
def get_report(id):
    require_roles(list(ALL_ROLES))
    return success_obj(report_out(_get_report_or_404(id)))


@bp.post("/wetland-permits/monitoring-reports/<id>/submit")
def submit_report(id):
    user_id, role = require_roles(["Applicant"])
    report = _get_report_or_404(id)
    permit = STORE["permits"].get(report["permit_id"])
    app = STORE["applications"].get(permit["application_id"]) \
        if permit else None
    check_ownership(user_id, role, app["applicant_id"] if app else None)
    body = get_body()
    # Tier 6: shape — coverage interval must be internally sane.
    coverage_start = req_datetime(body, "coverage_start")
    coverage_end = req_datetime(body, "coverage_end")
    findings_text = req_str(body, "findings_text")
    if not coverage_start < coverage_end:
        raise api_err("ERR_INVALID_REQUEST",
                      "coverage_start must be strictly before coverage_end")
    # Tier 7: submittable from DUE, OVERDUE, or DEFICIENT.
    if report["status"] not in ("DUE", "OVERDUE", "DEFICIENT"):
        raise api_err("ERR_REPORT_INVALID_STATE",
                      "submit requires a DUE, OVERDUE, or DEFICIENT report")
    # Priority 26: zero-gap contiguity with sibling reports.
    if report["period_index"] == 1:
        if coverage_start != permit["issue_date"]:
            raise api_err("ERR_COVERAGE_INTERVAL_CONFLICT",
                          "The first report's coverage_start must equal the "
                          "permit's issue_date")
    else:
        predecessor = next(
            (r for r in STORE["reports"].values()
             if r["permit_id"] == report["permit_id"]
             and r["period_index"] == report["period_index"] - 1), None)
        if predecessor is None \
                or predecessor["status"] not in ("SUBMITTED", "ACCEPTED") \
                or predecessor["coverage_end"] != coverage_start:
            raise api_err(
                "ERR_COVERAGE_INTERVAL_CONFLICT",
                "coverage_start must equal the coverage_end most recently "
                "submitted for the preceding period (no gaps, no overlaps)")
    report["coverage_start"] = coverage_start
    report["coverage_end"] = coverage_end
    report["findings_text"] = findings_text
    report["submitted_date"] = get_clock()
    report["status"] = "SUBMITTED"
    bump(report)
    return success_obj(report_out(report))


@bp.post("/wetland-permits/monitoring-reports/<id>/review")
def review_report(id):
    require_roles(["Reviewer"])
    report = _get_report_or_404(id)
    body = get_body()
    outcome = req_enum(body, "outcome", ("ACCEPTED", "DEFICIENT"))
    deficiency_notes = opt_str(body, "deficiency_notes")
    # Tier 6: DEFICIENT requires deficiency_notes.
    if outcome == "DEFICIENT" and not deficiency_notes:
        raise api_err("ERR_INVALID_REQUEST",
                      "deficiency_notes is required when the outcome is "
                      "DEFICIENT")
    # Tier 7: state.
    if report["status"] != "SUBMITTED":
        raise api_err("ERR_REPORT_INVALID_STATE",
                      "review requires a SUBMITTED report")
    if outcome == "ACCEPTED":
        report["outcome"] = "ACCEPTED"
        report["status"] = "ACCEPTED"
        bump(report)
        # When all five reports of the plan stand ACCEPTED, the plan
        # transitions ACTIVE -> COMPLETED.
        plan_reports = [r for r in STORE["reports"].values()
                        if r["plan_id"] == report["plan_id"]]
        if len(plan_reports) >= calc.MONITORING_REPORT_COUNT and all(
                r["status"] == "ACCEPTED" for r in plan_reports):
            plan = STORE["plans"].get(report["plan_id"])
            if plan is not None and plan["status"] == "ACTIVE":
                plan["status"] = "COMPLETED"
                bump(plan)
    else:
        report["outcome"] = "DEFICIENT"
        report["deficiency_notes"] = deficiency_notes
        report["status"] = "DEFICIENT"
        bump(report)
    return success_obj(report_out(report))

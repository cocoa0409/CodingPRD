"""Grant reports: compilation, submission and the partner's decision (PRD 3.9)."""

from flask import Blueprint, g

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint
from services import reports as report_service

bp = Blueprint("reports", __name__)

READ_ROLES = ("ProgramAdmin", "GrantOfficer", "PartnerLiaison")

DERIVED_FIELDS = (
    "installation_count",
    "household_count",
    "served_zone_count",
    "reimbursable_total_cents",
    "indirect_cents",
    "total_project_cents",
    "partner_match_required_cents",
    "grant_share_cents",
    "baseline_fire_rate_per_1000",
    "post_fire_rate_per_1000",
    "injury_delta",
    "retention_rate_pct",
)


def load_report(report_id):
    report = store.grant_reports.get(report_id)
    if report is None:
        raise ApiError("ERR_REPORT_NOT_FOUND")
    return report


@bp.post("/crr/grant-reports")
@endpoint("GrantOfficer")
def create_grant_report():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    grant_id = validation.req_str(body, "grant_id")
    period_start_date = validation.req_date(body, "period_start_date")
    period_end_date = validation.req_date(body, "period_end_date")
    is_final_report = validation.opt_bool(body, "is_final_report", default=False)

    grant = store.grants.get(grant_id)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND")

    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE")

    # PRD 3.9: the reported period lies entirely inside the grant's own period.
    if (
        period_start_date < grant["period_start_date"]
        or period_end_date > grant["period_end_date"]
    ):
        raise ApiError("ERR_REPORT_PERIOD_OUTSIDE_GRANT")

    row = db.stamp_new({})
    report = {
        "id": row["id"],
        "grant_id": grant_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "is_final_report": is_final_report,
        "status": "DRAFT",
        "revision_no": 0,
        "installation_count": 0,
        "household_count": 0,
        "served_zone_count": 0,
        "reimbursable_total_cents": 0,
        "indirect_cents": 0,
        "total_project_cents": 0,
        "partner_match_required_cents": 0,
        "grant_share_cents": 0,
        "baseline_fire_rate_per_1000": None,
        "post_fire_rate_per_1000": None,
        "injury_delta": None,
        "retention_rate_pct": None,
        "compiled_by_user_id": g.user_id,
        "submitted_by_user_id": None,
        "attestation_name": None,
        "submitted_at": None,
        "last_decision": None,
        "reviewer_note": None,
        "decided_at": None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.grant_reports[report["id"]] = report
    report_service.recompute_all(report)
    return response.ok_row(report, 201)


@bp.get("/crr/grant-reports")
@endpoint(*READ_ROLES)
def list_grant_reports():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.grant_reports.values()))
    for name in ("grant_id", "status"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    wanted_final = validation.filter_bool("is_final_report")
    if wanted_final is not None:
        rows = [r for r in rows if r["is_final_report"] == wanted_final]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/grant-reports/<report_id>")
@endpoint(*READ_ROLES)
def get_grant_report(report_id):
    return response.ok_row(load_report(report_id))


@bp.post("/crr/grant-reports/<report_id>/submit")
@endpoint("GrantOfficer")
def submit_grant_report(report_id):
    report = load_report(report_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    attestation_name = validation.req_str(body, "attestation_name")

    # Ladder step 7 - an officer cannot self-attest (PRD 2.1).
    if g.user_id == report["compiled_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_EDITABLE")

    grant = store.grants.get(report["grant_id"])
    if grant is None or grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE")

    # PRD 3.9: the ceiling and sufficiency checks read a full pre-submit
    # recompute; a rejected submission leaves the stored metrics untouched.
    snapshot = dict((key, report[key]) for key in DERIVED_FIELDS)
    report_service.recompute_all(report)
    try:
        remaining = grant["authorized_cents"] - grant["reported_grant_share_cents"]
        if report["grant_share_cents"] > remaining:
            raise ApiError("ERR_GRANT_SHARE_EXCEEDS_AUTHORIZED")
        if report["installation_count"] < 1:
            raise ApiError("ERR_NO_REPORTABLE_INSTALLATIONS")
    except ApiError:
        report.update(snapshot)
        raise

    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = g.user_id
    report["attestation_name"] = attestation_name
    report["submitted_at"] = util.clock.now()
    touch(report)
    return response.ok_row(report)


@bp.post("/crr/grant-reports/<report_id>/decision")
@endpoint("PartnerLiaison")
def decide_grant_report(report_id):
    report = load_report(report_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    decision = validation.req_enum(body, "decision", domain.DECISIONS)
    if decision == "RETURN":
        # PRD 3.9: the partner must say why on a return.
        reviewer_note = validation.req_str(body, "reviewer_note")
    else:
        reviewer_note = validation.opt_str(body, "reviewer_note")

    grant = store.grants.get(report["grant_id"])
    # Ladder step 6 - only the owning partner's liaison may decide.
    if grant is None or grant["partner_id"] != g.user_id:
        raise ApiError("ERR_PARTNER_NOT_OWNER")

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_EDITABLE")

    report["last_decision"] = decision
    report["reviewer_note"] = reviewer_note
    report["decided_at"] = util.clock.now()
    if decision == "ACCEPT":
        report["status"] = "ACCEPTED"
        touch(report)
        grant["reported_grant_share_cents"] = (
            grant["reported_grant_share_cents"] + report["grant_share_cents"]
        )
        touch(grant)
        if report["is_final_report"] and grant["reserved_cents"] == 0:
            # PRD 3.8: the only path to CLOSED, and only with no hold outstanding.
            grant["status"] = "CLOSED"
            touch(grant)
    else:
        report["status"] = "DRAFT"
        report["revision_no"] = report["revision_no"] + 1
        report["submitted_by_user_id"] = None
        report["attestation_name"] = None
        report["submitted_at"] = None
        touch(report)
    return response.ok_row(report)

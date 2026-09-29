"""Community benefits agreements, job reports and annual certification (PRD 3.7)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import (ALL_ROLES, by_created_desc, by_field_asc, endpoint,
                        filter_bool, filter_str, force_bump, paginate)
from services import calc, derive

bp = Blueprint("cbas", __name__)

MEASUREMENT_BASES = ["HEADCOUNT", "PAYROLL_HOURS"]


def load_cba(cba_id):
    row = db.cbas.get(cba_id)
    if row is None:
        fail("ERR_CBA_NOT_FOUND")
    return row


@bp.route("/nmtc/community-benefits-agreements", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True, status=201)
def create_cba():
    data = v.body()
    qalicb_id = v.req_str(data, "qalicb_id")
    award_id = v.req_str(data, "allocation_award_id")
    target_fte_count = v.req_int(data, "target_fte_count", 1)
    wage_floor = v.req_int(data, "wage_floor_cents_per_hour", 0)
    local_target = v.req_pct(data, "local_hire_pct_target")
    basis = v.req_enum(data, "measurement_basis", MEASUREMENT_BASES)

    qalicb = db.qalicbs.get(qalicb_id)
    if qalicb is None:
        fail("ERR_QALICB_NOT_FOUND")
    award = db.awards.get(award_id)
    if award is None:
        fail("ERR_ALLOCATION_AWARD_NOT_FOUND")
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if award["lifecycle_status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE")
    if qalicb["eligibility_status"] == "DISQUALIFIED":
        fail("ERR_QALICB_DISQUALIFIED")

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "qalicb_id": qalicb["id"],
        "allocation_award_id": award["id"],
        "target_fte_count": target_fte_count,
        "wage_floor_cents_per_hour": wage_floor,
        "local_hire_pct_target": local_target,
        "measurement_basis": basis,
        "agreement_start_at": now,
        "status": "ACTIVE",
        "consecutive_cure_required_count": 0,
        "last_certified_year": None,
        "latest_compliance_pct": calc.ZERO,
        "latest_local_hire_pct": calc.ZERO,
        "breached_at": None,
        "_seq": db.next_seq(),
    }
    db.cbas[row["id"]] = row
    return row, 201


@bp.route("/nmtc/community-benefits-agreements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_cbas():
    rows = list(db.cbas.values())
    rows = filter_str(rows, "qalicb_id")
    rows = filter_str(rows, "allocation_award_id")
    rows = filter_str(rows, "status")
    return by_created_desc(rows)


@bp.route("/nmtc/community-benefits-agreements/<cba_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_cba(cba_id):
    return load_cba(cba_id)


def _reports_of(cba_id):
    return [r for r in db.job_reports.values()
            if r["community_benefits_agreement_id"] == cba_id]


@bp.route("/nmtc/community-benefits-agreements/<cba_id>/job-reports",
          methods=["POST"])
@endpoint(["QALICBSponsor"], mutating=True, status=201)
def file_job_report(cba_id):
    data = v.body()
    period_start_at = v.req_instant(data, "period_start_at")
    period_end_at = v.req_instant(data, "period_end_at")
    if period_end_at <= period_start_at:
        fail("ERR_INVALID_REQUEST", "period_end_at must be after period_start_at")
    headcount = v.req_int(data, "headcount", 0)
    qualifying_headcount = v.req_int(data, "qualifying_headcount", 0)
    total_hours = v.req_int(data, "total_hours", 0)
    qualifying_hours = v.req_int(data, "qualifying_hours", 0)
    local_hires = v.req_int(data, "local_hires", 0)
    avg_hourly_wage_cents = v.req_int(data, "avg_hourly_wage_cents", 0)
    if qualifying_headcount > headcount:
        fail("ERR_INVALID_REQUEST", "qualifying_headcount may not exceed headcount")
    if qualifying_hours > total_hours:
        fail("ERR_INVALID_REQUEST", "qualifying_hours may not exceed total_hours")
    if local_hires > headcount:
        fail("ERR_INVALID_REQUEST", "local_hires may not exceed headcount")

    cba = load_cba(cba_id)
    qalicb = db.qalicbs[cba["qalicb_id"]]
    if g.user_id != qalicb["sponsor_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if cba["status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION")
    for other in _reports_of(cba["id"]):
        if (period_start_at <= other["period_end_at"]
                and other["period_start_at"] <= period_end_at):
            fail("ERR_REPORT_PERIOD_OVERLAP")

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "community_benefits_agreement_id": cba["id"],
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "headcount": headcount,
        "qualifying_headcount": qualifying_headcount,
        "total_hours": total_hours,
        "qualifying_hours": qualifying_hours,
        "local_hires": local_hires,
        "avg_hourly_wage_cents": avg_hourly_wage_cents,
        "wage_floor_met": avg_hourly_wage_cents >= cba["wage_floor_cents_per_hour"],
        "filed_by_user_id": g.user_id,
        "filed_at": now,
        "_seq": db.next_seq(),
    }
    db.job_reports[row["id"]] = row
    return row, 201


@bp.route("/nmtc/community-benefits-agreements/<cba_id>/job-reports",
          methods=["GET"])
@endpoint(ALL_ROLES)
def list_job_reports(cba_id):
    cba = load_cba(cba_id)
    rows = filter_bool(_reports_of(cba["id"]), "wage_floor_met")
    return by_field_asc(rows, "period_start_at")


@bp.route("/nmtc/community-benefits-agreements/<cba_id>/annual-certifications",
          methods=["POST"])
@endpoint(["ComplianceReviewer"], mutating=True, status=201)
def certify_year(cba_id):
    data = v.body()
    certification_year = v.req_int(data, "certification_year")
    window_start_at = v.req_instant(data, "window_start_at")
    window_end_at = v.req_instant(data, "window_end_at")

    cba = load_cba(cba_id)
    if cba["status"] in ("BREACHED", "CLOSED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    reports = [r for r in _reports_of(cba["id"])
               if window_start_at <= r["period_start_at"]
               and r["period_end_at"] <= window_end_at]
    reports.sort(key=lambda r: (r["period_start_at"], r["_seq"]))
    outcome = calc.job_quality(reports, cba["measurement_basis"],
                               cba["target_fte_count"],
                               cba["local_hire_pct_target"])

    classification = outcome["classification"]
    previous_status = cba["status"]
    cba["latest_compliance_pct"] = outcome["compliance_pct"]
    cba["latest_local_hire_pct"] = outcome["local_hire_pct"]
    now = clock.now()
    if classification == "CERTIFIED":
        cba["consecutive_cure_required_count"] = 0
        cba["last_certified_year"] = certification_year
        if previous_status == "CURE_REQUIRED":
            cba["status"] = "ACTIVE"
    elif classification == "CURE_REQUIRED":
        raised = cba["consecutive_cure_required_count"] + 1
        cba["consecutive_cure_required_count"] = raised
        if previous_status == "CURE_REQUIRED" and raised >= 2:
            cba["status"] = "BREACHED"
            cba["breached_at"] = now
        else:
            cba["status"] = "CURE_REQUIRED"
    else:
        cba["status"] = "BREACHED"
        cba["breached_at"] = now

    force_bump(cba)
    if cba["status"] == "BREACHED":
        force_bump(db.awards[cba["allocation_award_id"]])

    payload = {
        "community_benefits_agreement_id": cba["id"],
        "certification_year": certification_year,
        "measurement_basis": cba["measurement_basis"],
        "achieved_fte": outcome["achieved_fte"],
        "compliance_pct": outcome["compliance_pct"],
        "local_hire_pct": outcome["local_hire_pct"],
        "classification": classification,
        "report_count": outcome["report_count"],
        "excluded_wage_failing_report_count":
            outcome["excluded_wage_failing_report_count"],
        "resulting_status": cba["status"],
    }
    return payload, 201

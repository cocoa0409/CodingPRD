"""Programs, care managers and the accreditation file."""
from decimal import Decimal

from flask import Blueprint, request

import analytics
import core
import domain
import http_util as h
import serializers as S
from core import db

bp = Blueprint("program", __name__)

ALL_READ = ["ProgramAdmin", "CareManager", "ClinicalReviewer", "UtilizationAnalyst"]


@bp.post("/programs")
def create_program():
    h.authenticate(["ProgramAdmin"])
    data = h.body()
    name = h.req_str(data, "name")
    min_risk_tier = h.req_enum(data, "min_risk_tier", core.TIERS)
    variant = h.req_enum(data, "stratification_variant", core.STRAT_VARIANTS)
    credentials = h.req_str_array(data, "required_credential_levels",
                                  allowed=core.CREDENTIAL_LEVELS)
    staff_minute_budget = h.req_int(data, "staff_minute_budget", minimum=0)
    hourly_cost_cents = h.req_int(data, "hourly_cost_cents", minimum=0)
    cohort_benchmark = h.req_int(data, "cohort_benchmark_pmpm_cents", minimum=0)
    review_interval = h.opt_int(data, "care_plan_review_interval_days", default=90)
    toc_hours = h.opt_int(data, "toc_outreach_hours", default=48)
    referral_days = h.opt_int(data, "referral_loop_days", default=30)

    rec = domain.base_record()
    rec.update({
        "name": name,
        "min_risk_tier": min_risk_tier,
        "stratification_variant": variant,
        "required_credential_levels": credentials,
        "care_plan_review_interval_days": review_interval,
        "toc_outreach_hours": toc_hours,
        "referral_loop_days": referral_days,
        "staff_minute_budget": staff_minute_budget,
        "hourly_cost_cents": hourly_cost_cents,
        "cohort_benchmark_pmpm_cents": cohort_benchmark,
        "committed_staff_minutes": 0,
        "delivered_staff_minutes": 0,
    })
    db.programs[rec["id"]] = rec
    return h.ok(S.program_out(rec), 201)


@bp.get("/programs/<program_id>")
def read_program(program_id):
    h.authenticate(ALL_READ)
    rec = domain.get_program(program_id)
    return h.ok(S.program_out(rec))


@bp.get("/programs/<program_id>/accreditation-file")
def accreditation_file(program_id):
    h.authenticate(["ProgramAdmin", "UtilizationAnalyst"])
    program = domain.get_program(program_id)
    return h.ok(analytics.build_accreditation_file(program))


@bp.post("/care-managers")
def create_care_manager():
    h.authenticate(["ProgramAdmin"])
    data = h.body()
    full_name = h.req_str(data, "full_name")
    credential = h.req_enum(data, "credential_level", core.CREDENTIAL_LEVELS)
    states = h.req_str_array(data, "licensed_state_codes",
                             item_check=h.is_state_code)
    capacity = h.req_decimal(data, "capacity_points", gt=0, places=1)

    rec = domain.base_record()
    rec.update({
        "full_name": full_name,
        "credential_level": credential,
        "licensed_state_codes": states,
        "capacity_points": capacity,
        "assigned_caseload_points": Decimal("0.0"),
        "capacity_status": "OPEN",
        "active_enrollment_count": 0,
    })
    db.care_managers[rec["id"]] = rec
    return h.ok(S.care_manager_out(rec), 201)


@bp.get("/care-managers/<manager_id>")
def read_care_manager(manager_id):
    h.authenticate(ALL_READ)
    rec = domain.get_care_manager(manager_id)
    return h.ok(S.care_manager_out(rec))


@bp.get("/care-managers")
def list_care_managers():
    h.authenticate(["ProgramAdmin", "UtilizationAnalyst"])
    limit, offset = h.pagination()
    rows = list(db.care_managers.values())
    capacity_status = request.args.get("capacity_status")
    if capacity_status is not None:
        rows = [r for r in rows if r["capacity_status"] == capacity_status]
    credential = request.args.get("credential_level")
    if credential is not None:
        rows = [r for r in rows if r["credential_level"] == credential]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.care_manager_out(r) for r in page], limit, offset, total)

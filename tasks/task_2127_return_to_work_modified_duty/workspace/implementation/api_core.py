"""Workers, claims, clinicians, restriction intake, supervisors, training and
the transitional job bank."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
import serialize
from auth import (require_roles, own_employee_id, own_claim, own_supervisor_id,
                  own_training_record, own_restriction_set, own_provider_body)
from errors import fail
from response import ok, created, ok_list, paginate
from store import db, stamp_new, touch, ordered
from util import parse_date
from validators import (body_of, str_field, enum_field, int_field, num_field,
                        bool_field, date_field, not_inverted, pagination,
                        query_enum, query_str, bad)

bp = Blueprint("core", __name__)

BENEFIT_TIERS = ("TIER_A", "TIER_B", "TIER_C")
EMPLOYMENT_STATUSES = ("ACTIVE", "ON_LEAVE", "SEPARATED")
CLAIM_STATUSES = ("OPEN", "RTW_ELIGIBLE", "SUSPENDED", "CLOSED")
CLAIM_DIRECTIVES = ("RTW_ELIGIBLE", "SUSPENDED", "CLOSED")
CREDENTIAL_STATUSES = ("VERIFIED", "PROVISIONAL", "REVOKED")
RS_STATUSES = ("DRAFT", "SUBMITTED", "CLARIFICATION_REQUESTED", "VERIFIED",
               "ACTIVE", "SUPERSEDED", "EXPIRED")
CURRICULA = ("RTW_CORE", "RESTRICTION_HANDLING", "REINJURY_RESPONSE")
RECORD_STATUSES = ("VALID", "EXPIRING_SOON", "EXPIRED", "SUPERSEDED")
JOB_STATUSES = ("OPEN", "PAUSED", "RETIRED")
RISK_CLASSES = ("LOW", "MEDIUM", "HIGH")


# ============================================================== employees
@bp.post("/rtw/employees")
@require_roles("ProgramAdmin")
def create_employee():
    body = body_of()
    full_name = str_field(body, "full_name")
    employee_number = str_field(body, "employee_number", min_len=1, max_len=32)
    department_code = str_field(body, "department_code")
    wage = int_field(body, "pre_injury_weekly_wage_cents", minimum=1)
    hours = num_field(body, "pre_injury_weekly_hours", gt=0, le=80)
    benefit_tier = enum_field(body, "benefit_tier", BENEFIT_TIERS)
    employment_status = enum_field(body, "employment_status",
                                   EMPLOYMENT_STATUSES, required=False,
                                   default="ACTIVE")
    # priority 42
    if any(e["employee_number"] == employee_number for e in db.employees.values()):
        fail("ERR_DUPLICATE_IDENTIFIER", "employee_number already exists.")
    row = stamp_new({
        "full_name": full_name,
        "employee_number": employee_number,
        "department_code": department_code,
        "pre_injury_weekly_wage_cents": wage,
        "pre_injury_weekly_hours": hours,
        "benefit_tier": benefit_tier,
        "employment_status": employment_status,
    })
    db.employees[row["id"]] = row
    return created(serialize.employee(row))


def _employee_or_404(employee_id):
    row = db.employees.get(employee_id)
    if row is None:
        fail("ERR_EMPLOYEE_NOT_FOUND", "No Employee row matches that id.")
    return row


def _claim_or_404(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", "No Claim row matches that id.")
    return row


def _provider_or_404(provider_id):
    row = db.providers.get(provider_id)
    if row is None:
        fail("ERR_PROVIDER_NOT_FOUND", "No TreatingProvider row matches that id.")
    return row


def _rs_or_404(rs_id):
    row = db.restriction_sets.get(rs_id)
    if row is None:
        fail("ERR_RESTRICTION_SET_NOT_FOUND",
             "No RestrictionSet row matches that id.")
    return row


def _supervisor_or_404(supervisor_id):
    row = db.supervisors.get(supervisor_id)
    if row is None:
        fail("ERR_SUPERVISOR_NOT_FOUND", "No Supervisor row matches that id.")
    return row


def _training_or_404(record_id):
    row = db.training_records.get(record_id)
    if row is None:
        fail("ERR_TRAINING_RECORD_NOT_FOUND",
             "No TrainingRecord row matches that id.")
    return row


def _job_or_404(job_id):
    row = db.jobs.get(job_id)
    if row is None:
        fail("ERR_JOB_NOT_FOUND", "No TransitionalJob row matches that id.")
    return row


@bp.get("/rtw/employees/<employee_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Supervisor", "Employee")
def read_employee(employee_id):
    row = _employee_or_404(employee_id)
    own_employee_id(employee_id)
    return ok(serialize.employee(row))


# ================================================================= claims
@bp.post("/rtw/employees/<employee_id>/claims")
@require_roles("ProgramAdmin", "ClaimAdjuster")
def create_claim(employee_id):
    body = body_of()
    claim_number = str_field(body, "claim_number")
    adjuster_user_id = str_field(body, "adjuster_user_id")
    injury_date = date_field(body, "injury_date")
    _employee_or_404(employee_id)
    if any(c["claim_number"] == claim_number for c in db.claims.values()):
        fail("ERR_DUPLICATE_IDENTIFIER", "claim_number already exists.")
    row = stamp_new({
        "employee_id": employee_id,
        "claim_number": claim_number,
        "adjuster_user_id": adjuster_user_id,
        "injury_date": injury_date.isoformat(),
        "claim_status": "OPEN",
        "max_authorized_weekly_cost_cents": 0,
    })
    db.claims[row["id"]] = row
    return created(serialize.claim(row))


@bp.get("/rtw/employees/<employee_id>/claims")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Employee")
def list_employee_claims(employee_id):
    limit, offset = pagination()
    claim_status = query_enum("claim_status", CLAIM_STATUSES)
    _employee_or_404(employee_id)
    own_employee_id(employee_id)
    rows = [c for c in db.claims.values() if c["employee_id"] == employee_id]
    if claim_status:
        rows = [c for c in rows if c["claim_status"] == claim_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.claim(r) for r in page], limit, offset, total)


@bp.get("/rtw/claims/<claim_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Employee")
def read_claim(claim_id):
    row = _claim_or_404(claim_id)
    own_claim(row)
    return ok(serialize.claim(row))


@bp.post("/rtw/claims/<claim_id>/adjuster-authorization")
@require_roles("ClaimAdjuster", "ProgramAdmin")
def adjuster_authorization(claim_id):
    body = body_of()
    ceiling = int_field(body, "max_authorized_weekly_cost_cents", minimum=0)
    directive = enum_field(body, "claim_status_directive", CLAIM_DIRECTIVES)
    row = _claim_or_404(claim_id)
    row["max_authorized_weekly_cost_cents"] = ceiling
    row["claim_status"] = directive
    touch(row)
    return ok(serialize.claim(row))


# ====================================================== treating providers
@bp.post("/rtw/treating-providers")
@require_roles("ProgramAdmin")
def create_provider():
    body = body_of()
    full_name = str_field(body, "full_name")
    npi = str_field(body, "npi")
    if len(npi) != 10 or not npi.isdigit():
        bad("'npi' must be exactly 10 digits.")
    specialty = str_field(body, "specialty")
    credential_status = enum_field(body, "credential_status",
                                   CREDENTIAL_STATUSES, required=False,
                                   default="PROVISIONAL")
    if any(p["npi"] == npi for p in db.providers.values()):
        fail("ERR_DUPLICATE_IDENTIFIER", "npi already exists.")
    row = stamp_new({
        "full_name": full_name,
        "npi": npi,
        "specialty": specialty,
        "credential_status": credential_status,
    })
    db.providers[row["id"]] = row
    return created(serialize.provider(row))


@bp.get("/rtw/treating-providers/<provider_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "TreatingProvider")
def read_provider(provider_id):
    return ok(serialize.provider(_provider_or_404(provider_id)))


@bp.patch("/rtw/treating-providers/<provider_id>")
@require_roles("ProgramAdmin")
def patch_provider(provider_id):
    body = body_of()
    credential_status = enum_field(body, "credential_status",
                                   CREDENTIAL_STATUSES)
    row = _provider_or_404(provider_id)
    row["credential_status"] = credential_status
    touch(row)
    return ok(serialize.provider(row))


# ====================================================== restriction intake
@bp.post("/rtw/claims/<claim_id>/restriction-sets")
@require_roles("TreatingProvider", "ProgramAdmin")
def create_restriction_set(claim_id):
    body = body_of()
    treating_provider_id = str_field(body, "treating_provider_id")
    effective_from = date_field(body, "effective_from")
    valid_through = date_field(body, "valid_through")
    not_inverted(effective_from, valid_through, "effective_from", "valid_through")
    max_lift = num_field(body, "max_lift_lbs", ge=0)
    max_standing = num_field(body, "max_continuous_standing_minutes", ge=0)
    max_hours = num_field(body, "max_hours_per_day", gt=0, le=12)
    keyboard = num_field(body, "keyboard_minutes_per_hour", ge=0, le=60)
    overhead = bool_field(body, "overhead_reach_allowed")
    driving = bool_field(body, "driving_allowed")
    expected_claim_version = int_field(body, "expected_claim_version")
    # priority 4
    claim = _claim_or_404(claim_id)
    # priority 5
    provider = _provider_or_404(treating_provider_id)
    # priority 6
    own_provider_body(treating_provider_id)
    # priority 17
    if provider["credential_status"] != "VERIFIED":
        fail("ERR_PROVIDER_CREDENTIAL_REVOKED",
             "The treating provider is not credentialed as VERIFIED.")
    # priority 41
    if expected_claim_version != claim["version"]:
        fail("ERR_STALE_CLAIM_VERSION",
             "expected_claim_version does not match the claim's version.")
    row = stamp_new({
        "claim_id": claim_id,
        "treating_provider_id": treating_provider_id,
        "supersedes_restriction_set_id": None,
        "status": "DRAFT",
        "effective_from": effective_from.isoformat(),
        "valid_through": valid_through.isoformat(),
        "max_lift_lbs": max_lift,
        "max_continuous_standing_minutes": max_standing,
        "max_hours_per_day": max_hours,
        "keyboard_minutes_per_hour": keyboard,
        "overhead_reach_allowed": overhead,
        "driving_allowed": driving,
        "clarification_note": None,
        "clarification_round_count": 0,
    })
    db.restriction_sets[row["id"]] = row
    touch(claim)
    return created(serialize.restriction_set(row))


@bp.get("/rtw/claims/<claim_id>/restriction-sets")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "TreatingProvider")
def list_claim_restriction_sets(claim_id):
    limit, offset = pagination()
    status = query_enum("status", RS_STATUSES)
    _claim_or_404(claim_id)
    rows = [r for r in db.restriction_sets.values() if r["claim_id"] == claim_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.restriction_set(r) for r in page], limit, offset,
                   total)


@bp.get("/rtw/restriction-sets")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse")
def list_restriction_sets():
    limit, offset = pagination()
    status = query_enum("status", RS_STATUSES)
    claim_id = query_str("claim_id")
    treating_provider_id = query_str("treating_provider_id")
    supersedes = query_str("supersedes_restriction_set_id")
    if treating_provider_id is not None:
        _provider_or_404(treating_provider_id)
    if supersedes is not None:
        _rs_or_404(supersedes)
    rows = list(db.restriction_sets.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if treating_provider_id is not None:
        rows = [r for r in rows
                if r["treating_provider_id"] == treating_provider_id]
    if supersedes is not None:
        rows = [r for r in rows
                if r["supersedes_restriction_set_id"] == supersedes]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.restriction_set(r) for r in page], limit, offset,
                   total)


@bp.get("/rtw/restriction-sets/<rs_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "TreatingProvider")
def read_restriction_set(rs_id):
    row = _rs_or_404(rs_id)
    own_restriction_set(row)
    return ok(serialize.restriction_set(row))


@bp.post("/rtw/restriction-sets/<rs_id>/submit")
@require_roles("TreatingProvider", "ProgramAdmin")
def submit_restriction_set(rs_id):
    row = _rs_or_404(rs_id)
    own_restriction_set(row)
    domain.check_terminal("restriction_set", row["status"])
    domain.check_from_state(row["status"], ("DRAFT", "CLARIFICATION_REQUESTED"))
    provider = db.providers.get(row["treating_provider_id"])
    if not provider or provider["credential_status"] != "VERIFIED":
        fail("ERR_PROVIDER_CREDENTIAL_REVOKED",
             "The treating provider is not credentialed as VERIFIED.")
    row["status"] = "SUBMITTED"
    touch(row)
    return ok(serialize.restriction_set(row))


@bp.post("/rtw/restriction-sets/<rs_id>/request-clarification")
@require_roles("OccHealthNurse", "RTWCoordinator")
def request_clarification(rs_id):
    body = body_of()
    note = str_field(body, "note")
    row = _rs_or_404(rs_id)
    domain.check_terminal("restriction_set", row["status"])
    domain.check_from_state(row["status"], ("SUBMITTED",))
    row["status"] = "CLARIFICATION_REQUESTED"
    row["clarification_note"] = note
    row["clarification_round_count"] += 1
    touch(row)
    return ok(serialize.restriction_set(row))


@bp.post("/rtw/restriction-sets/<rs_id>/verify")
@require_roles("OccHealthNurse")
def verify_restriction_set(rs_id):
    row = _rs_or_404(rs_id)
    domain.check_terminal("restriction_set", row["status"])
    domain.check_from_state(row["status"], ("SUBMITTED",))
    provider = db.providers.get(row["treating_provider_id"])
    if not provider or provider["credential_status"] != "VERIFIED":
        fail("ERR_PROVIDER_CREDENTIAL_REVOKED",
             "The treating provider is not credentialed as VERIFIED.")
    row["status"] = "VERIFIED"
    touch(row)
    return ok(serialize.restriction_set(row))


@bp.post("/rtw/restriction-sets/<rs_id>/activate")
@require_roles("RTWCoordinator", "OccHealthNurse")
def activate_restriction_set(rs_id):
    row = _rs_or_404(rs_id)
    domain.check_terminal("restriction_set", row["status"])
    domain.check_from_state(row["status"], ("VERIFIED",))
    # priority 18
    if parse_date(row["valid_through"]) < db.today():
        fail("ERR_RESTRICTION_WINDOW_INVALID",
             "valid_through is earlier than the logical clock's calendar date.")
    prior = calc.active_restriction_set(row["claim_id"])
    # CASCADE L1
    row["status"] = "ACTIVE"
    row["supersedes_restriction_set_id"] = prior["id"] if prior else None
    touch(row)
    if prior is not None:
        # CASCADE L2
        prior["status"] = "SUPERSEDED"
        touch(prior)
        # CASCADE L3
        for placement in calc.placements_of_restriction_set(prior["id"]):
            if placement["placement_status"] not in ("ADJUSTER_PENDING",
                                                     "ACTIVE",
                                                     "PROGRESSION_HOLD"):
                continue
            job = db.jobs[placement["transitional_job_id"]]
            if not domain.job_demand_breach(row, job):
                continue
            placement["placement_status"] = "SUSPENDED"
            placement["suspension_reason"] = "RESTRICTION_CONFLICT"
            touch(placement)
            # CASCADE L4
            for review in calc.reviews_of_placement(placement["id"]):
                if review["review_status"] in ("SCHEDULED", "IN_REVIEW"):
                    review["review_status"] = "ESCALATED"
                    touch(review)
            domain.new_case_review(placement["id"], "RESTRICTION_CONFLICT",
                                   "system", 3)
    return ok(serialize.restriction_set(row))


# ============================================================ supervisors
@bp.post("/rtw/supervisors")
@require_roles("ProgramAdmin")
def create_supervisor():
    body = body_of()
    full_name = str_field(body, "full_name")
    department_code = str_field(body, "department_code")
    row = stamp_new({
        "full_name": full_name,
        "department_code": department_code,
        "oversight_status": "ACTIVE",
        "strike_forgiveness_points": 0,
    })
    db.supervisors[row["id"]] = row
    return created(serialize.supervisor(row))


@bp.get("/rtw/supervisors/<supervisor_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def read_supervisor(supervisor_id):
    row = _supervisor_or_404(supervisor_id)
    own_supervisor_id(supervisor_id)
    return ok(serialize.supervisor(row))


@bp.post("/rtw/supervisors/<supervisor_id>/training-records")
@require_roles("ProgramAdmin", "Supervisor")
def create_training_record(supervisor_id):
    body = body_of()
    curriculum_code = enum_field(body, "curriculum_code", CURRICULA)
    completed_on = date_field(body, "completed_on")
    valid_through = date_field(body, "valid_through")
    supervisor = _supervisor_or_404(supervisor_id)
    own_supervisor_id(supervisor_id)
    for prior in calc.training_records_of_supervisor(supervisor_id):
        if (prior["curriculum_code"] == curriculum_code
                and prior["record_status"] != "SUPERSEDED"):
            prior["record_status"] = "SUPERSEDED"
            touch(prior)
    row = stamp_new({
        "supervisor_id": supervisor_id,
        "curriculum_code": curriculum_code,
        "completed_on": completed_on.isoformat(),
        "valid_through": valid_through.isoformat(),
        "record_status": "VALID",
        "renewal_count": 0,
    })
    db.training_records[row["id"]] = row
    touch(supervisor)
    return created(serialize.training_record(row))


@bp.get("/rtw/supervisors/<supervisor_id>/training-records")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def list_training_records(supervisor_id):
    limit, offset = pagination()
    curriculum_code = query_enum("curriculum_code", CURRICULA)
    record_status = query_enum("record_status", RECORD_STATUSES)
    _supervisor_or_404(supervisor_id)
    own_supervisor_id(supervisor_id)
    rows = [t for t in db.training_records.values()
            if t["supervisor_id"] == supervisor_id]
    if curriculum_code:
        rows = [t for t in rows if t["curriculum_code"] == curriculum_code]
    if record_status:
        rows = [t for t in rows if t["record_status"] == record_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.training_record(r) for r in page], limit, offset,
                   total)


@bp.get("/rtw/training-records/<record_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def read_training_record(record_id):
    row = _training_or_404(record_id)
    own_training_record(row)
    return ok(serialize.training_record(row))


@bp.post("/rtw/training-records/<record_id>/renew")
@require_roles("ProgramAdmin", "Supervisor")
def renew_training_record(record_id):
    body = body_of()
    new_valid_through = date_field(body, "new_valid_through")
    if new_valid_through <= db.today():
        bad("'new_valid_through' must be later than the current clock date.")
    row = _training_or_404(record_id)
    own_training_record(row)
    domain.check_terminal("training_record", row["record_status"])
    domain.check_from_state(row["record_status"],
                            ("VALID", "EXPIRING_SOON", "EXPIRED"))
    row["record_status"] = "VALID"
    row["valid_through"] = new_valid_through.isoformat()
    row["renewal_count"] += 1
    touch(row)
    supervisor = db.supervisors.get(row["supervisor_id"])
    if (supervisor is not None and row["curriculum_code"] == "RTW_CORE"
            and supervisor["oversight_status"] == "SUSPENDED"):
        supervisor["strike_forgiveness_points"] = \
            calc.supervisor_compliance_strike_points(supervisor["id"])
        supervisor["oversight_status"] = "ACTIVE"
        touch(supervisor)
        for job in calc.ordered_jobs_of_supervisor(supervisor["id"]):
            if job["job_status"] == "PAUSED":
                job["job_status"] = "OPEN"
                touch(job)
    return ok(serialize.training_record(row))


# ====================================================== transitional jobs
@bp.post("/rtw/transitional-jobs")
@require_roles("ProgramAdmin", "RTWCoordinator")
def create_job():
    body = body_of()
    supervisor_id = str_field(body, "supervisor_id")
    title = str_field(body, "title")
    department_code = str_field(body, "department_code")
    seat_capacity = int_field(body, "seat_capacity", minimum=1)
    demand_lift = num_field(body, "demand_lift_lbs", ge=0)
    demand_standing = num_field(body, "demand_standing_minutes", ge=0)
    demand_hours = num_field(body, "demand_hours_per_day", gt=0, le=12)
    demand_keyboard = num_field(body, "demand_keyboard_minutes_per_hour",
                                ge=0, le=60)
    hourly_rate = int_field(body, "hourly_rate_cents", minimum=1)
    requires_overhead = bool_field(body, "requires_overhead_reach",
                                   required=False, default=False)
    requires_driving = bool_field(body, "requires_driving", required=False,
                                  default=False)
    risk_class = enum_field(body, "risk_class", RISK_CLASSES, required=False,
                            default="LOW")
    _supervisor_or_404(supervisor_id)
    row = stamp_new({
        "supervisor_id": supervisor_id,
        "title": title,
        "department_code": department_code,
        "seat_capacity": seat_capacity,
        "demand_lift_lbs": demand_lift,
        "demand_standing_minutes": demand_standing,
        "demand_hours_per_day": demand_hours,
        "demand_keyboard_minutes_per_hour": demand_keyboard,
        "requires_overhead_reach": requires_overhead,
        "requires_driving": requires_driving,
        "hourly_rate_cents": hourly_rate,
        "risk_class": risk_class,
        "job_status": "OPEN",
    })
    db.jobs[row["id"]] = row
    return created(serialize.transitional_job(row))


@bp.get("/rtw/transitional-jobs")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def list_jobs():
    limit, offset = pagination()
    supervisor_id = query_str("supervisor_id")
    department_code = query_str("department_code")
    job_status = query_enum("job_status", JOB_STATUSES)
    risk_class = query_enum("risk_class", RISK_CLASSES)
    rows = list(db.jobs.values())
    if supervisor_id is not None:
        rows = [j for j in rows if j["supervisor_id"] == supervisor_id]
    if department_code is not None:
        rows = [j for j in rows if j["department_code"] == department_code]
    if job_status:
        rows = [j for j in rows if j["job_status"] == job_status]
    if risk_class:
        rows = [j for j in rows if j["risk_class"] == risk_class]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.transitional_job(r) for r in page], limit, offset,
                   total)


@bp.get("/rtw/transitional-jobs/<job_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def read_job(job_id):
    return ok(serialize.transitional_job(_job_or_404(job_id)))


@bp.patch("/rtw/transitional-jobs/<job_id>")
@require_roles("ProgramAdmin", "RTWCoordinator")
def patch_job(job_id):
    body = body_of()
    job_status = enum_field(body, "job_status", JOB_STATUSES, required=False)
    seat_capacity = int_field(body, "seat_capacity", required=False, minimum=1)
    row = _job_or_404(job_id)
    if job_status is not None:
        row["job_status"] = job_status
    if seat_capacity is not None:
        row["seat_capacity"] = seat_capacity
    touch(row)
    return ok(serialize.transitional_job(row))

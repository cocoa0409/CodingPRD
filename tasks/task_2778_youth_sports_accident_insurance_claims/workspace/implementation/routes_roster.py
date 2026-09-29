"""Participants, enrollments and family health plans."""

from flask import Blueprint, g

import auth
import constants as C
import db
import guards
import response
import services
import util
import validation as v
from errors import ApiError

bp = Blueprint("roster", __name__)


# --------------------------------------------------------------- participants

@bp.post("/participants")
def create_participant():
    auth.require_roles(["LeagueAdministrator"])
    body = v.json_body()
    auth.early_ownership("league", body.get("league_id"))
    league_id = v.req_id(body, "league_id")
    first_name = v.req_str(body, "first_name")
    last_name = v.req_str(body, "last_name")
    date_of_birth = v.req_instant(body, "date_of_birth")
    guardian_email = v.req_str(body, "guardian_email")
    guardian_phone = v.req_str(body, "guardian_phone", required=False, default=None)
    league = guards.resolve("league", league_id)
    auth.check_ownership(league)
    row = db.new_row("participants", {
        "league_id": league["id"],
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": util.format_datetime(date_of_birth),
        "guardian_email": guardian_email,
        "guardian_phone": guardian_phone,
        "roster_status": "ROSTERED",
        "enrolled_policy_count": 0,
    })
    response.mark_fresh(row)
    return response.respond_obj(row, 201)


@bp.get("/participants/<participant_id>")
def get_participant(participant_id):
    auth.require_roles([
        "ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer", "GuardianPortal",
    ])
    row = guards.resolve("participant", participant_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/participants")
def list_participants():
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator"])
    limit, offset = v.pagination()
    league_id = v.query_str("league_id")
    roster_status = v.query_enum("roster_status", C.ROSTER_STATUSES)
    rows = db.all_rows("participants")
    if league_id is not None:
        rows = [r for r in rows if r["league_id"] == league_id]
    if roster_status is not None:
        rows = [r for r in rows if r["roster_status"] == roster_status]
    return response.respond_list(rows, limit, offset)


# ---------------------------------------------------------------- enrollments

@bp.post("/enrollments")
def create_enrollment():
    auth.require_roles(["LeagueAdministrator"])
    body = v.json_body()
    auth.early_ownership("league_policy", body.get("league_policy_id"))
    participant_id = v.req_id(body, "participant_id")
    policy_id = v.req_id(body, "league_policy_id")
    enrolled_on = v.req_instant(body, "enrolled_on_date")
    participant = guards.resolve("participant", participant_id)
    policy = guards.resolve("league_policy", policy_id)
    auth.check_ownership(policy)
    if participant["league_id"] != policy["league_id"]:
        raise ApiError("ERR_SCOPE_MISMATCH")
    guards.require_policy_in_force(policy, ("BOUND", "ACTIVE"))
    guards.require_league_sanctioned(policy)
    guards.require_not_frozen(policy)
    guards.require_not_claims_review(policy)
    if not guards.instant_in_term(policy, enrolled_on):
        raise ApiError("ERR_ENROLLMENT_OUTSIDE_TERM")
    for existing in db.enrollments_of_policy(policy["id"]):
        if existing["participant_id"] == participant["id"] and existing["status"] == "ENROLLED":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT")
    row = db.new_row("enrollments", {
        "participant_id": participant["id"],
        "league_policy_id": policy["id"],
        "enrolled_on_date": util.format_datetime(enrolled_on),
        "status": "ENROLLED",
        "withdrawn_on_date": None,
        "lifetime_cat_benefit_used_cents": 0,
        "coverage_status": "COVERED",
    })
    response.mark_fresh(row)
    services.recompute_participant(participant)
    return response.respond_obj(row, 201)


@bp.get("/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer"])
    row = guards.resolve("enrollment", enrollment_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/enrollments")
def list_enrollments():
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer"])
    limit, offset = v.pagination()
    participant_id = v.query_str("participant_id")
    policy_id = v.query_str("league_policy_id")
    status = v.query_enum("status", C.ENROLLMENT_STATUSES)
    coverage_status = v.query_enum("coverage_status", C.ENROLLMENT_COVERAGE_STATUSES)
    rows = db.all_rows("enrollments")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if policy_id is not None:
        rows = [r for r in rows if r["league_policy_id"] == policy_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if coverage_status is not None:
        rows = [r for r in rows if r["coverage_status"] == coverage_status]
    return response.respond_list(rows, limit, offset)


@bp.post("/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    auth.require_roles(["LeagueAdministrator"])
    enrollment = guards.resolve("enrollment", enrollment_id)
    auth.check_ownership(enrollment)
    body = v.json_body()
    v.req_str(body, "withdrawal_note")
    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE")
    for claim in db.claims_of_enrollment(enrollment["id"]):
        if claim["adjudication_status"] in C.OPEN_ADJUDICATION_STATUSES:
            raise ApiError("ERR_OPEN_CLAIMS_ON_ENROLLMENT")
    services.touch(
        enrollment,
        status="WITHDRAWN",
        withdrawn_on_date=db.now_iso(),
        coverage_status="WITHDRAWN_NO_COVERAGE",
    )
    services.recompute_enrollment(enrollment)
    services.recompute_participant(db.get("participants", enrollment["participant_id"]))
    return response.respond_obj(enrollment)


# ------------------------------------------------------- family health plans

@bp.post("/family-health-plans")
def create_family_health_plan():
    auth.require_roles(["GuardianPortal", "ClaimsExaminer"])
    body = v.json_body()
    auth.early_ownership("participant", body.get("participant_id"))
    participant_id = v.req_id(body, "participant_id")
    carrier_name = v.req_str(body, "carrier_name")
    policy_number = v.req_str(body, "policy_number")
    plan_type = v.req_enum(body, "plan_type", C.PLAN_TYPES)
    deductible = v.req_int(body, "individual_deductible_cents", minimum=0)
    coinsurance = v.req_int(body, "coinsurance_bps", minimum=0, maximum=10000)
    effective = v.req_instant(body, "effective_date")
    termination = v.req_instant(body, "termination_date", required=False, default=None)
    participant = guards.resolve("participant", participant_id)
    auth.check_ownership(participant)
    row = db.new_row("family_health_plans", {
        "participant_id": participant["id"],
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "plan_type": plan_type,
        "individual_deductible_cents": deductible,
        "coinsurance_bps": coinsurance,
        "effective_date": util.format_datetime(effective),
        "termination_date": util.format_datetime(termination),
        "coverage_state": "ACTIVE",
        "verification_status": "UNVERIFIED",
        "verified_at": None,
        "verified_by_user_id": None,
    })
    response.mark_fresh(row)
    row["coverage_state"] = services.plan_coverage_state(row)
    return response.respond_obj(row, 201)


@bp.get("/family-health-plans/<family_health_plan_id>")
def get_family_health_plan(family_health_plan_id):
    auth.require_roles(["ProgramAdministrator", "ClaimsExaminer", "GuardianPortal"])
    row = guards.resolve("family_health_plan", family_health_plan_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/family-health-plans")
def list_family_health_plans():
    auth.require_roles(["ProgramAdministrator", "ClaimsExaminer", "GuardianPortal"])
    limit, offset = v.pagination()
    participant_id = v.query_str("participant_id")
    verification_status = v.query_enum("verification_status", C.PLAN_VERIFICATION_STATUSES)
    coverage_state = v.query_enum("coverage_state", C.COVERAGE_STATES)
    rows = db.all_rows("family_health_plans")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    if coverage_state is not None:
        rows = [r for r in rows if r["coverage_state"] == coverage_state]
    return response.respond_list(rows, limit, offset)


@bp.post("/family-health-plans/<family_health_plan_id>/verification")
def verify_family_health_plan(family_health_plan_id):
    auth.require_roles(["ClaimsExaminer"])
    plan = guards.resolve("family_health_plan", family_health_plan_id)
    body = v.json_body()
    decision = v.req_enum(body, "decision", C.PLAN_DECISIONS)
    v.req_str(body, "note")
    if plan["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_FAMILY_PLAN_STATE")
    services.touch(
        plan,
        verification_status=decision,
        verified_at=db.now_iso(),
        verified_by_user_id=g.user_id,
    )
    return response.respond_obj(plan)

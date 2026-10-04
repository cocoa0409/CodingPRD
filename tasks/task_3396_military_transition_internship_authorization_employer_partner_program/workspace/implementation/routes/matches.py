from flask import Blueprint, request

import constants
import db
import services
from errors import fail
from middleware import (
    auth_context,
    require_role,
    body,
    locked,
    req_str,
    req_int,
    req_enum,
    req_date,
    opt_str,
)
from response import success, paginate
from util import serialize

bp = Blueprint("matches", __name__)


def _get_match(mid):
    match = db.store.matches.get(mid)
    if match is None:
        fail("ERR_MATCH_NOT_FOUND", "InternshipMatch %s does not exist" % mid)
    return match


def _validate_objectives_payload(data):
    raw = data.get("learning_objectives")
    if not isinstance(raw, list) or len(raw) == 0:
        fail("ERR_VALIDATION", "learning_objectives must be a non-empty array")
    seen_codes = set()
    normalized = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "each learning objective must be an object")
        code = entry.get("objective_code")
        if not isinstance(code, str):
            fail("ERR_VALIDATION", "objective_code is required and must be a string")
        if code in seen_codes:
            fail("ERR_VALIDATION", "objective_code values must be unique within the plan")
        seen_codes.add(code)
        description = entry.get("description")
        if not isinstance(description, str):
            fail("ERR_VALIDATION", "description is required and must be a string")
        weight = entry.get("weight_hours")
        if weight is None or isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            fail("ERR_VALIDATION", "weight_hours must be an integer > 0")
        status = entry.get("status")
        if status is not None and status not in constants.OBJECTIVE_STATUSES:
            fail("ERR_VALIDATION", "objective status must be PENDING, ACHIEVED, or EXCUSED")
        normalized.append(
            {
                "objective_code": code,
                "description": description,
                "weight_hours": weight,
                "status": "PENDING",
            }
        )
    return normalized


@bp.route("/internship-matches", methods=["POST"])
@locked
def create_match():
    uid, role = auth_context()
    data = body()
    application_id = req_str(data, "internship_application_id")
    opening_id = req_str(data, "employer_opening_id")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    expected_version = req_int(data, "expected_employer_opening_version")
    require_role(role, ["EmployerRep"])
    application = db.store.applications.get(application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND", "InternshipApplication %s does not exist" % application_id)
    opening = db.store.openings.get(opening_id)
    if opening is None:
        fail("ERR_OPENING_NOT_FOUND", "EmployerOpening %s does not exist" % opening_id)
    if expected_version != opening["version"]:
        fail("ERR_STALE_VERSION", "expected_employer_opening_version does not match current version")
    if uid != opening["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the opening's employer_id")
    if application["status"] != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED", "Application is not APPROVED")
    if opening["status"] != "OPEN":
        fail("ERR_OPENING_NOT_OPEN", "Opening is not OPEN")
    employer = db.store.employers.get(opening["employer_id"])
    if employer is None or employer["authorization_status"] != "AUTHORIZED":
        fail("ERR_EMPLOYER_NOT_AUTHORIZED", "Employer is not AUTHORIZED")
    member = db.store.members.get(application["service_member_id"])
    if member is None:
        fail("ERR_MEMBER_NOT_FOUND", "Applicant ServiceMember does not exist")
    if member["service_status"] != "ACTIVE_DUTY":
        fail("ERR_MEMBER_NOT_ON_ACTIVE_DUTY", "Applicant is not ACTIVE_DUTY")
    clock_date = db.now().date()
    if start_date < clock_date:
        fail("ERR_START_DATE_IN_PAST", "start_date is earlier than the logical clock date")
    duration_days = (end_date - start_date).days
    if duration_days < constants.MIN_INTERNSHIP_DURATION_DAYS:
        fail("ERR_DURATION_BELOW_MINIMUM", "duration_days is below the 30-day minimum")
    installation = db.store.installations.get(member["home_installation_id"])
    headroom = (member["separation_date"] - start_date).days - constants.SEPARATION_BUFFER_DAYS
    effective_max = min(installation["max_internship_duration_days"], headroom)
    if duration_days > effective_max:
        fail("ERR_DURATION_EXCEEDS_POLICY", "duration_days exceeds the effective maximum")
    if not set(opening["required_skills"]).issubset(set(member["skills"])):
        fail("ERR_SKILLS_MISMATCH", "Member skills do not cover the opening's required_skills")
    if (
        opening["location_type"] == "ON_SITE"
        and installation is not None
        and opening["region_code"] != installation["region_code"]
    ):
        fail("ERR_LOCATION_CONSTRAINT_VIOLATION", "ON_SITE region does not match member region")
    for m in db.store.matches.values():
        if (
            m["service_member_id"] == member["id"]
            and m["match_status"] in constants.NON_TERMINAL_MATCH_STATUSES
            and not (end_date <= m["start_date"] or start_date >= m["end_date"])
        ):
            fail("ERR_MEMBER_SCHEDULE_OVERLAP", "Member already holds an overlapping match")
    overlapping_on_opening = 0
    for m in db.store.matches.values():
        if (
            m["employer_opening_id"] == opening["id"]
            and m["match_status"] in constants.NON_TERMINAL_MATCH_STATUSES
            and not (end_date <= m["start_date"] or start_date >= m["end_date"])
        ):
            overlapping_on_opening += 1
    if overlapping_on_opening >= opening["capacity"]:
        fail("ERR_OPENING_AT_CAPACITY", "Opening is at capacity for the proposed interval")
    ent = db.base_entity()
    ent.update(
        {
            "internship_application_id": application_id,
            "employer_opening_id": opening_id,
            "service_member_id": member["id"],
            "employer_id": opening["employer_id"],
            "installation_id": member["home_installation_id"],
            "start_date": start_date,
            "end_date": end_date,
            "match_status": "PROPOSED",
            "plan_status": "PLAN_DRAFT",
            "learning_objectives": [],
            "supervisor_name": None,
            "weekly_hours": None,
            "plan_revision_count": 0,
            "flagged_wage_violation": False,
            "resolution_ratio": 1.0,
            "mastery_ratio": 1.0,
            "completed_at": None,
            "termination_reason": None,
            "installation_decision_by": None,
            "installation_decision_reason": None,
        }
    )
    db.store.matches[ent["id"]] = ent
    services.recompute_filled_count(opening)
    services.touch(opening)
    services.recompute_active_match_count(member)
    return success(serialize(ent), status=201)


@bp.route("/internship-matches", methods=["GET"])
@locked
def list_matches():
    auth_context()
    items = sorted(db.store.matches.values(), key=lambda e: e["_seq"])
    for field in (
        "internship_application_id",
        "employer_opening_id",
        "service_member_id",
        "employer_id",
        "installation_id",
        "match_status",
    ):
        value = request.args.get(field)
        if value is not None:
            items = [m for m in items if m[field] == value]
    page, pagination = paginate(items)
    return success([serialize(m) for m in page], pagination=pagination)


@bp.route("/internship-matches/<mid>", methods=["GET"])
@locked
def get_match(mid):
    auth_context()
    return success(serialize(_get_match(mid)))


@bp.route("/internship-matches/<mid>/installation-decision", methods=["POST"])
@locked
def installation_decision(mid):
    uid, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", {"APPROVE", "DENY"})
    reason = opt_str(data, "reason")
    if decision == "DENY" and reason is None:
        fail("ERR_VALIDATION", "reason is required when decision is DENY")
    require_role(role, ["InstallationAuthority"])
    match = _get_match(mid)
    if match["match_status"] != "PROPOSED":
        fail("ERR_MATCH_NOT_PROPOSED", "Match is not PROPOSED")
    employer = db.store.employers.get(match["employer_id"])
    if decision == "APPROVE":
        if match["plan_status"] != "PLAN_APPROVED":
            fail("ERR_PLAN_NOT_APPROVED", "Training plan is not PLAN_APPROVED")
        if employer is None or employer["authorization_status"] != "AUTHORIZED":
            fail("ERR_EMPLOYER_NOT_AUTHORIZED", "Employer is not AUTHORIZED")
        member = db.store.members.get(match["service_member_id"])
        if member is None or member["service_status"] != "ACTIVE_DUTY":
            fail("ERR_MEMBER_NOT_ON_ACTIVE_DUTY", "Member is not ACTIVE_DUTY")
        match["match_status"] = "INSTALLATION_APPROVED"
    else:
        if employer is None or employer["authorization_status"] != "AUTHORIZED":
            fail("ERR_EMPLOYER_NOT_AUTHORIZED", "Employer is not AUTHORIZED")
        match["match_status"] = "INSTALLATION_DENIED"
        opening = db.store.openings.get(match["employer_opening_id"])
        if opening is not None:
            services.recompute_filled_count(opening)
        member = db.store.members.get(match["service_member_id"])
        if member is not None:
            services.recompute_active_match_count(member)
    match["installation_decision_by"] = uid
    match["installation_decision_reason"] = reason
    services.touch(match)
    return success(serialize(match))


@bp.route("/internship-matches/<mid>/submit-plan", methods=["POST"])
@locked
def submit_plan(mid):
    uid, role = auth_context()
    data = body()
    objectives = _validate_objectives_payload(data)
    supervisor_name = req_str(data, "supervisor_name")
    weekly_hours = req_int(data, "weekly_hours", min_value=1)
    require_role(role, ["EmployerRep"])
    match = _get_match(mid)
    if uid != match["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the match's employer_id")
    if match["match_status"] != "PROPOSED":
        fail("ERR_MATCH_NOT_PROPOSED", "Match is not PROPOSED")
    if (
        match["plan_status"] == "PLAN_RETURNED"
        and match["plan_revision_count"] >= constants.MAX_PLAN_REVISIONS
    ):
        fail("ERR_MAX_PLAN_REVISIONS_REACHED", "Plan revision budget exhausted")
    match["learning_objectives"] = objectives
    match["supervisor_name"] = supervisor_name
    match["weekly_hours"] = weekly_hours
    match["plan_status"] = "PLAN_SUBMITTED"
    services.recompute_ratios(match)
    services.touch(match)
    return success(serialize(match))


@bp.route("/internship-matches/<mid>/review-plan", methods=["POST"])
@locked
def review_plan(mid):
    uid, role = auth_context()
    data = body()
    outcome = req_enum(data, "outcome", {"APPROVE", "RETURN"})
    opt_str(data, "feedback")  # optional; validated for type, not stored
    require_role(role, ["InstallationAuthority"])
    match = _get_match(mid)
    if match["plan_status"] != "PLAN_SUBMITTED":
        fail("ERR_PLAN_NOT_SUBMITTED", "Plan is not PLAN_SUBMITTED")
    if outcome == "APPROVE":
        match["plan_status"] = "PLAN_APPROVED"
    else:
        match["plan_status"] = "PLAN_RETURNED"
        match["plan_revision_count"] += 1
    services.touch(match)
    return success(serialize(match))


@bp.route("/internship-matches/<mid>/terminate", methods=["POST"])
@locked
def terminate_match(mid):
    uid, role = auth_context()
    data = body()
    reason = req_enum(data, "reason", constants.CALLER_TERMINATION_REASONS)
    require_role(role, ["EmployerRep", "InstallationAuthority"])
    match = _get_match(mid)
    if role == "EmployerRep" and uid != match["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the match's employer_id")
    if match["match_status"] not in constants.TERMINABLE_MATCH_STATUSES:
        fail("ERR_MATCH_NOT_TERMINABLE", "Match is not in a terminable state")
    match["match_status"] = "TERMINATED_EARLY"
    match["termination_reason"] = reason
    opening = db.store.openings.get(match["employer_opening_id"])
    if opening is not None:
        services.recompute_filled_count(opening)
    member = db.store.members.get(match["service_member_id"])
    if member is not None:
        services.recompute_active_match_count(member)
    services.touch(match)
    return success(serialize(match))


@bp.route("/internship-matches/<mid>/complete", methods=["POST"])
@locked
def complete_match(mid):
    uid, role = auth_context()
    body()
    require_role(role, ["InstallationAuthority"])
    match = _get_match(mid)
    if match["match_status"] != "ACTIVE":
        fail("ERR_MATCH_NOT_ACTIVE", "Match is not ACTIVE")
    if db.now().date() < match["end_date"]:
        fail("ERR_COMPLETION_DATE_NOT_REACHED", "Logical clock date is before end_date")
    objectives = match["learning_objectives"]
    if any(o["status"] not in ("ACHIEVED", "EXCUSED") for o in objectives):
        fail("ERR_OBJECTIVES_INCOMPLETE", "Not all learning objectives are resolved")
    duration_days = (match["end_date"] - match["start_date"]).days
    expected_reports = duration_days // constants.SUPERVISION_CADENCE_DAYS
    actual_reports = sum(
        1
        for r in db.store.supervision_reports.values()
        if r["internship_match_id"] == match["id"]
    )
    if actual_reports < expected_reports:
        fail("ERR_INSUFFICIENT_SUPERVISION", "Supervision coverage is below the required cadence")
    if match["mastery_ratio"] < constants.MIN_MASTERY_RATIO:
        fail("ERR_MASTERY_BELOW_THRESHOLD", "mastery_ratio is below 0.75")
    match["match_status"] = "COMPLETED"
    match["completed_at"] = db.now()
    opening = db.store.openings.get(match["employer_opening_id"])
    if opening is not None:
        services.recompute_filled_count(opening)
    member = db.store.members.get(match["service_member_id"])
    if member is not None:
        services.recompute_active_match_count(member)
    services.touch(match)
    return success(serialize(match))


def _list_children(mid, store_attr):
    auth_context()
    match = _get_match(mid)
    items = sorted(
        [r for r in getattr(db.store, store_attr).values() if r["internship_match_id"] == match["id"]],
        key=lambda e: e["_seq"],
    )
    page, pagination = paginate(items)
    return success([serialize(r) for r in page], pagination=pagination)


@bp.route("/internship-matches/<mid>/supervision-reports", methods=["GET"])
@locked
def list_supervision_reports(mid):
    return _list_children(mid, "supervision_reports")


@bp.route("/internship-matches/<mid>/wage-records", methods=["GET"])
@locked
def list_wage_records(mid):
    return _list_children(mid, "wage_records")


@bp.route("/internship-matches/<mid>/conversion-records", methods=["GET"])
@locked
def list_conversion_records(mid):
    return _list_children(mid, "conversions")

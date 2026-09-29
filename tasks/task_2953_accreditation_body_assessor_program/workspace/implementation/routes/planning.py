"""Assessment planning, witnessing and closing the assessment (PRD 3.5, 3.6)."""

from flask import Blueprint

import calc
import domain
import store
from auth import ASSESSMENT_MANAGER, LEAD_ASSESSOR, TECHNICAL_EXPERT, endpoint
from envelope import created, single
from errors import ApiError
from validators import (body, date_field, enum_field, instant_field, int_field,
                        string_field)

bp = Blueprint("planning", __name__)

PLAN_MODES = ("ON_SITE", "REMOTE", "HYBRID")
ACTIVITY_TYPES = ("TESTING", "CALIBRATION", "INSPECTION", "MANAGEMENT_REVIEW", "INTERNAL_AUDIT")
DELIVERY_MODES = ("ON_SITE", "REMOTE")
RESULT_STATUSES = ("COMPLETED", "ABORTED")
SESSION_OUTCOMES = ("SATISFACTORY", "DEFICIENT")


def recompute_plan(plan, application):
    pinned = domain.pinned(application)
    days = calc.effort_days(len(application["requested_scope_lines"]),
                            pinned["witness_min_count"],
                            plan["on_site_days"], plan["remote_days"])
    fees = calc.assessment_fee(plan["on_site_days"], plan["remote_days"],
                              days["witness_days_planned"], days["travel_days"],
                              pinned["complexity_multiplier"])
    plan.update(days)
    plan.update(fees)
    return plan


@bp.post("/accreditation/applications/<application_id>/assessment-plans")
@endpoint([ASSESSMENT_MANAGER, LEAD_ASSESSOR])
def create_plan(user_id, role, application_id):
    payload = body()
    expected_version = int_field(payload, "expected_application_version", 0, None)
    mode = enum_field(payload, "mode", PLAN_MODES)
    planned_start = date_field(payload, "planned_start")
    planned_end = date_field(payload, "planned_end")
    on_site_days = int_field(payload, "on_site_days", 0, 30)
    remote_days = int_field(payload, "remote_days", 0, 30)

    if mode == "REMOTE" and on_site_days != 0:
        raise ApiError("ERR_INVALID_REQUEST", "on_site_days must be 0 when mode is REMOTE")
    if mode == "ON_SITE" and remote_days != 0:
        raise ApiError("ERR_INVALID_REQUEST", "remote_days must be 0 when mode is ON_SITE")
    if planned_end < planned_start:
        raise ApiError("ERR_INVALID_DATE_RANGE", "planned_end must not fall before planned_start")

    application = domain.find("applications", application_id)
    if expected_version != application["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    if application["suspension_blocked"] or application["status"] not in domain.PLANNING_STATUSES:
        raise ApiError("ERR_APPLICATION_STATE_INVALID", "this cycle does not permit planning")

    plan = store.insert("plans", {
        "application_id": application_id,
        "mode": mode,
        "planned_start": payload["planned_start"],
        "planned_end": payload["planned_end"],
        "on_site_days": on_site_days,
        "remote_days": remote_days,
        "witness_days_planned": 0,
        "core_days": 0,
        "travel_days": 0,
        "total_effort_days": 0,
        "fee_line_on_site_cents": 0,
        "fee_line_remote_cents": 0,
        "fee_line_witness_cents": 0,
        "fee_line_travel_cents": 0,
        "assessment_fee_cents": 0,
        "status": "DRAFT",
        "approved_at": None,
        "revision_note": None,
        "superseded_by_plan_id": None,
    })
    recompute_plan(plan, application)

    for other in store.ordered(domain.plans_of(application_id)):
        if other["id"] == plan["id"]:
            continue
        if other["status"] == "DRAFT":
            other["status"] = "CANCELLED"
            other["superseded_by_plan_id"] = plan["id"]
            store.touch(other)

    store.touch(application)
    return created(store.public(plan))


@bp.post("/accreditation/assessment-plans/<plan_id>/approve")
@endpoint([ASSESSMENT_MANAGER])
def approve_plan(user_id, role, plan_id):
    plan = domain.find("plans", plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "only a DRAFT plan may be approved")

    application = domain.application_of_plan(plan)
    if application["suspension_blocked"] or application["status"] not in domain.PLANNING_STATUSES:
        raise ApiError("ERR_APPLICATION_STATE_INVALID", "this cycle does not permit approval")

    scheme = store.get("schemes", application["scheme_id"])
    if scheme is None:
        raise ApiError("ERR_SCHEME_NOT_FOUND")
    if scheme["status"] != "PUBLISHED":
        raise ApiError("ERR_SCHEME_NOT_PUBLISHED")
    if scheme["rule_revision"] != application["pinned_scheme_rule_revision"]:
        raise ApiError("ERR_SCHEME_VERSION_SUPERSEDED")
    if not domain.has_confirmed_lead(application["id"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the cycle has no CONFIRMED LEAD_ASSESSOR")
    if plan["mode"] == "REMOTE":
        if not scheme["remote_assessment_allowed"]:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "this programme forbids remote assessment")
        if scheme["witness_min_count"] != 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "a REMOTE plan cannot discharge a witnessing obligation")

    recompute_plan(plan, application)
    plan["status"] = "APPROVED"
    plan["approved_at"] = store.now_iso()
    store.touch(plan)

    if application["status"] == "TEAM_ASSIGNED":
        application["status"] = "PLANNED"
        application["planned_effort_days"] = plan["total_effort_days"]
        store.touch(application)

    return single(store.public(plan))


@bp.post("/accreditation/assessment-plans/<plan_id>/return-to-draft")
@endpoint([ASSESSMENT_MANAGER])
def return_plan_to_draft(user_id, role, plan_id):
    payload = body()
    revision_note = string_field(payload, "revision_note", 1, 500)

    plan = domain.find("plans", plan_id)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "only an APPROVED plan may be returned")
    application = domain.application_of_plan(plan)
    if application["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the cycle must be PLANNED to return its plan")
    for session in domain.sessions_of_plan(plan_id):
        if session["status"] == "COMPLETED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the plan is locked by completed witnessing evidence")

    plan["status"] = "DRAFT"
    plan["revision_note"] = revision_note
    plan["approved_at"] = None
    store.touch(plan)

    for session in store.ordered(domain.sessions_of_plan(plan_id)):
        if session["status"] == "SCHEDULED":
            domain.abort_session(session, "plan returned to draft")

    application["status"] = "TEAM_ASSIGNED"
    application["planned_effort_days"] = None
    store.touch(application)

    return single(store.public(plan))


@bp.post("/accreditation/assessment-plans/<plan_id>/witness-sessions")
@endpoint([ASSESSMENT_MANAGER, LEAD_ASSESSOR])
def schedule_session(user_id, role, plan_id):
    payload = body()
    assessor_id = string_field(payload, "assessor_id", 1)
    activity_type = enum_field(payload, "activity_type", ACTIVITY_TYPES)
    site_ref = string_field(payload, "site_ref", 1, 80)
    delivery_mode = enum_field(payload, "delivery_mode", DELIVERY_MODES)
    starts_at = instant_field(payload, "starts_at")
    ends_at = instant_field(payload, "ends_at")

    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_DATE_RANGE", "ends_at must be strictly after starts_at")

    plan = domain.find("plans", plan_id)
    assessor = domain.find("assessors", assessor_id)
    application = domain.application_of_plan(plan)

    if application["suspension_blocked"]:
        raise ApiError("ERR_APPLICATION_STATE_INVALID", "the owning cycle is frozen")
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED")

    for other in store.rows("sessions"):
        if other["assessor_id"] != assessor_id:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if starts_at < other["_ends"] and other["_starts"] < ends_at:
            raise ApiError("ERR_ASSESSOR_SCHEDULE_CONFLICT")

    organization_id = application["organization_id"]
    for other in store.rows("sessions"):
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if other["delivery_mode"] != "ON_SITE":
            continue
        if other["site_ref"] != site_ref:
            continue
        if domain.organization_of_session(other) == organization_id:
            continue
        gap = (starts_at.date() - other["_ends"].date()).days
        if gap <= calc.SITE_BUFFER_DAYS:
            raise ApiError("ERR_SITE_BUFFER_CONFLICT")

    day_count = calc.session_day_count(starts_at, ends_at)
    if assessor["committed_witness_days"] + day_count > assessor["annual_witness_capacity_days"]:
        raise ApiError("ERR_ASSESSOR_CAPACITY_EXCEEDED")
    if delivery_mode == "REMOTE" and not domain.pinned(application)["remote_assessment_allowed"]:
        raise ApiError("ERR_REMOTE_WITNESS_NOT_PERMITTED")

    session = store.insert("sessions", {
        "plan_id": plan_id,
        "assessor_id": assessor_id,
        "activity_type": activity_type,
        "site_ref": site_ref,
        "delivery_mode": delivery_mode,
        "starts_at": payload["starts_at"],
        "ends_at": payload["ends_at"],
        "day_count": day_count,
        "status": "SCHEDULED",
        "outcome": None,
        "evidence_note": None,
        "_starts": starts_at,
        "_ends": ends_at,
    })
    domain.commit_witness_days(assessor, day_count)
    return created(store.public(session))


@bp.post("/accreditation/witness-sessions/<session_id>/outcome")
@endpoint([LEAD_ASSESSOR, TECHNICAL_EXPERT])
def record_session_outcome(user_id, role, session_id):
    payload = body()
    result_status = enum_field(payload, "result_status", RESULT_STATUSES)
    outcome = enum_field(payload, "outcome", SESSION_OUTCOMES, required=False)
    evidence_note = string_field(payload, "evidence_note", 1, 500, required=False)

    if result_status == "COMPLETED" and outcome is None:
        raise ApiError("ERR_INVALID_REQUEST", "a COMPLETED result requires an outcome")
    if result_status == "ABORTED" and outcome is not None:
        raise ApiError("ERR_INVALID_REQUEST", "an ABORTED result must not carry an outcome")

    session = domain.find("sessions", session_id)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a SCHEDULED session may record a result")

    application = domain.application_of_session(session)
    if result_status == "COMPLETED" and application["suspension_blocked"]:
        raise ApiError("ERR_APPLICATION_STATE_INVALID", "the owning cycle is frozen")

    if user_id != session["assessor_id"] \
            or domain.confirmed_assignment(application["id"], user_id) is None:
        raise ApiError("ERR_NOT_ASSIGNED_TEAM_MEMBER")

    plan = store.get("plans", session["plan_id"])
    if result_status == "COMPLETED" and plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED")

    if result_status == "ABORTED":
        session["evidence_note"] = evidence_note
        domain.abort_session(session, evidence_note)
        return single(store.public(session))

    session["status"] = "COMPLETED"
    session["outcome"] = outcome
    session["evidence_note"] = evidence_note
    store.touch(session)

    for qualification in store.ordered(domain.qualifications_of(session["assessor_id"])):
        if qualification["scheme_id"] == application["scheme_id"] \
                and qualification["status"] == "GRANTED":
            qualification["last_witness_on"] = store.today_iso()
            store.touch(qualification)

    domain.refresh_completed_witness_count(application)
    if application["status"] == "PLANNED":
        application["status"] = "IN_ASSESSMENT"
        store.touch(application)

    return single(store.public(session))


@bp.post("/accreditation/applications/<application_id>/close-assessment")
@endpoint([ASSESSMENT_MANAGER])
def close_assessment(user_id, role, application_id):
    application = domain.find("applications", application_id)
    if application["suspension_blocked"] or application["status"] != "IN_ASSESSMENT":
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "the cycle must be IN_ASSESSMENT to be closed")

    plan = domain.approved_plan(application_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_APPROVED")

    pinned = domain.pinned(application)
    completed = [s for s in domain.sessions_of_plan(plan["id"]) if s["status"] == "COMPLETED"]
    completed_days = sum(s["day_count"] for s in completed)
    if application["completed_witness_session_count"] < pinned["witness_min_count"] \
            or completed_days < plan["witness_days_planned"]:
        raise ApiError("ERR_WITNESS_COVERAGE_INSUFFICIENT")

    plan["status"] = "EXECUTED"
    store.touch(plan)

    if application["nc_blocking_open_count"] >= 1:
        application["status"] = "NC_OPEN"
        store.touch(application)
    else:
        application["status"] = "DECISION_PENDING"
        store.touch(application)
        domain.create_decision_record(application)

    return single(store.public(application))

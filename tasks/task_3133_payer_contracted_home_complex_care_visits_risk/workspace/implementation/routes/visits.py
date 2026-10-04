"""Visit + VisitAssessment endpoints per PRD §3.5, §2.9, §2.10."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_state, err_input, err_stale,
                    err_not_assigned, ERR_VISIT_NOT_FOUND,
                    ERR_ENROLLMENT_NOT_FOUND, ERR_ASSESSMENT_NOT_FOUND,
                    ERR_VISIT_NOT_SCHEDULED, ERR_VISIT_NOT_EN_ROUTE,
                    ERR_VISIT_NOT_IN_PROGRESS, ERR_VISIT_NOT_CANCELLABLE,
                    ERR_VISIT_NOT_CANCELLED, ERR_VISIT_TIME_OVERLAP,
                    ERR_MAX_RESCHEDULES_EXCEEDED, ERR_VISIT_WINDOW_NOT_PAST,
                    ERR_ASSESSMENT_NOT_DRAFT, ERR_ASSESSMENT_NOT_SUBMITTED,
                    ERR_ASSESSMENT_INCOMPLETE,
                    ERR_PCP_COORDINATION_NOTE_REQUIRED,
                    ERR_CARE_TEAM_NOT_ACTIVE, ERR_ENROLLMENT_NOT_ACTIVE,
                    ERR_INVALID_REQUEST, ERR_CANCELLATION_REASON_REQUIRED)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.calculations import compute_final_burden, refresh_member_risk
from services.clock import now_clock, now_iso, fmt_ts, parse_ts
from services.measurements import (get_or_create_measurement, bump_counter,
                                   recompute_pcp_coordination_rate,
                                   recompute_composite)
from services.resources import base_fields, touch
from services.selectors import routine_selector
from services.validation import (get_json_body, require_string, require_enum,
                                 require_int, require_field)

bp = Blueprint("visits", __name__)

MAX_RESCHEDULES = 2

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "Clinician", "PerformanceAnalyst"]
COORDINATOR = ["CareCoordinator"]
CLINICIAN = ["Clinician"]
VISIT_TYPES = {"INITIAL_ASSESSMENT", "ROUTINE_FOLLOWUP", "URGENT",
               "POST_ED_FOLLOWUP"}
CANCELLATION_REASONS = {"MEMBER_REQUEST", "CLINICIAN_UNAVAILABLE",
                        "MEMBER_NO_SHOW", "ENROLLMENT_ENDED"}
IN_FLIGHT = ("SCHEDULED", "EN_ROUTE", "IN_PROGRESS")


def _get_visit_or_404(visit_id):
    v = db.visits.get(visit_id)
    if v is None:
        raise err_not_found(ERR_VISIT_NOT_FOUND, "Visit")
    return v


def _get_assessment_for_visit(visit_id):
    for a in db.assessments.values():
        if a.get("visit_id") == visit_id:
            return a
    return None


def _check_assigned_clinician(user_id, visit):
    if user_id != visit.get("clinician_id"):
        raise err_not_assigned()


def _overlap_conflict(clinician_id, new_start, new_end, exclude_visit_id=None):
    """Half-open [start, end) overlap against the clinician's other in-flight
    visits (PRD §2.10)."""
    for other in db.visits.values():
        if other.get("clinician_id") != clinician_id:
            continue
        if exclude_visit_id is not None and other["id"] == exclude_visit_id:
            continue
        if other.get("status") not in IN_FLIGHT:
            continue
        o_start = parse_ts(other.get("scheduled_start"))
        o_end = parse_ts(other.get("scheduled_end"))
        if o_start is None or o_end is None:
            continue
        if new_start < o_end and o_start < new_end:
            return True
    return False


def _measurement_for_visit(v):
    member = db.members.get(v.get("member_id"))
    if member is None:
        return None
    program = db.care_programs.get(member.get("care_program_id"))
    period = int(program.get("current_period_index") or 0) if program else 0
    return get_or_create_measurement(member.get("payer_contract_id"),
                                     member["id"], period)


@bp.route("/visits", methods=["POST"])
def create_visit():
    require_roles(COORDINATOR)
    body = get_json_body()
    enrollment_id = require_string(body, "enrollment_id")
    visit_type = require_enum(body, "visit_type", VISIT_TYPES)
    scheduled_start_raw = require_string(body, "scheduled_start")
    scheduled_end_raw = require_string(body, "scheduled_end")

    # Body FK existence (rung 4)
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err_not_found(ERR_ENROLLMENT_NOT_FOUND, "MemberEnrollment")

    # URGENT is rejected at this endpoint (PRD §3.5) — use /urgent-episodes.
    if visit_type == "URGENT":
        raise err_input(ERR_INVALID_REQUEST,
                        "URGENT visits are dispatched via /urgent-episodes")

    start = parse_ts(scheduled_start_raw, "scheduled_start")
    end = parse_ts(scheduled_end_raw, "scheduled_end")
    if not (end > start):
        raise err_input(ERR_INVALID_REQUEST,
                        "scheduled_end must be strictly later than scheduled_start")

    # Enrollment must be ACTIVE
    if enrollment.get("status") != "ACTIVE":
        raise err_state(ERR_ENROLLMENT_NOT_ACTIVE,
                        "Enrollment must be ACTIVE for visit creation")

    # Care team must be ACTIVE (rung 7; while SUSPENDED → ERR_CARE_TEAM_NOT_ACTIVE)
    team = None
    for t in db.care_teams.values():
        if t.get("enrollment_id") == enrollment_id:
            team = t
            break
    if team is None or team.get("status") != "ACTIVE":
        raise err_state(ERR_CARE_TEAM_NOT_ACTIVE,
                        "Care team must be ACTIVE for visit creation")

    member = db.members.get(enrollment.get("member_id"))
    program = db.care_programs.get(member.get("care_program_id")) if member else None

    # Selector (rung 10) — runs before the overlap check per PRD §3.5
    clinician = routine_selector(program, visit_type)

    # Overlap check against the chosen clinician's in-flight visits (rung 9)
    if _overlap_conflict(clinician["id"], start, end):
        raise err_state(ERR_VISIT_TIME_OVERLAP,
                        "Visit window overlaps another in-flight visit")

    v = base_fields()
    v.update({
        "enrollment_id": enrollment_id,
        "member_id": enrollment.get("member_id"),
        "clinician_id": clinician["id"],
        "visit_type": visit_type,
        "scheduled_start": fmt_ts(start),
        "scheduled_end": fmt_ts(end),
        "actual_start": None,
        "actual_end": None,
        "cancellation_reason": None,
        "reschedule_count": 0,
        "status": "SCHEDULED",
    })
    db.visits[v["id"]] = v

    clinician["active_daily_visit_count"] = int(
        clinician.get("active_daily_visit_count") or 0) + 1
    touch(clinician)
    return success_object(serializers.visit(v), status=201)


@bp.route("/visits", methods=["GET"])
def list_visits():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.visits.values())
    eid = request.args.get("enrollment_id")
    if eid:
        items = [v for v in items if v.get("enrollment_id") == eid]
    mid = request.args.get("member_id")
    if mid:
        items = [v for v in items if v.get("member_id") == mid]
    cid = request.args.get("clinician_id")
    if cid:
        items = [v for v in items if v.get("clinician_id") == cid]
    s = request.args.get("status")
    if s:
        items = [v for v in items if v.get("status") == s]
    vt = request.args.get("visit_type")
    if vt:
        items = [v for v in items if v.get("visit_type") == vt]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.visit(v) for v in page],
                        limit, offset, total)


@bp.route("/visits/<visitId>", methods=["GET"])
def get_visit(visitId):
    require_roles(READ_ROLES)
    v = _get_visit_or_404(visitId)
    return success_object(serializers.visit(v))


@bp.route("/visits/<visitId>/depart", methods=["POST"])
def depart_visit(visitId):
    user_id, _ = require_roles(CLINICIAN)
    v = _get_visit_or_404(visitId)
    if v.get("status") != "SCHEDULED":
        raise err_state(ERR_VISIT_NOT_SCHEDULED,
                        "Visit must be SCHEDULED to depart")
    _check_assigned_clinician(user_id, v)
    v["status"] = "EN_ROUTE"
    touch(v)
    return success_object(serializers.visit(v))


@bp.route("/visits/<visitId>/arrive", methods=["POST"])
def arrive_visit(visitId):
    user_id, _ = require_roles(CLINICIAN)
    v = _get_visit_or_404(visitId)
    if v.get("status") != "EN_ROUTE":
        raise err_state(ERR_VISIT_NOT_EN_ROUTE,
                        "Visit must be EN_ROUTE to arrive")
    _check_assigned_clinician(user_id, v)
    v["status"] = "IN_PROGRESS"
    v["actual_start"] = now_iso()
    touch(v)
    return success_object(serializers.visit(v))


MED_REC_FIELDS = ("medications_reviewed", "discrepancies_found",
                  "high_risk_med_changes")
SAFETY_FIELDS = ("fall_risk_score", "home_hazard_count", "adl_impairment_count")
SOCIAL_FIELDS = ("food_insecurity", "housing_instability",
                 "transportation_barrier", "social_isolation_score")


def _validate_assessment_object(body, field, subfields):
    obj = body.get(field)
    if obj is None:
        return None
    if not isinstance(obj, dict):
        raise err_input(ERR_INVALID_REQUEST, "%s must be an object" % field)
    for sf in subfields:
        if sf not in obj or obj.get(sf) is None:
            raise err_input(ERR_INVALID_REQUEST,
                            "%s.%s is required" % (field, sf))
    return obj


def _assessment_complete(a):
    for field, subfields in (("medication_reconciliation", MED_REC_FIELDS),
                             ("safety_evaluation", SAFETY_FIELDS),
                             ("social_needs_screening", SOCIAL_FIELDS)):
        obj = a.get(field)
        if not isinstance(obj, dict):
            return False
        for sf in subfields:
            if obj.get(sf) is None:
                return False
    return True


@bp.route("/visits/<visitId>/assessment", methods=["POST"])
def upsert_assessment(visitId):
    user_id, _ = require_roles(CLINICIAN)
    v = _get_visit_or_404(visitId)
    _check_assigned_clinician(user_id, v)
    body = get_json_body()

    med_rec = _validate_assessment_object(body, "medication_reconciliation",
                                          MED_REC_FIELDS)
    safety = _validate_assessment_object(body, "safety_evaluation",
                                         SAFETY_FIELDS)
    social = _validate_assessment_object(body, "social_needs_screening",
                                         SOCIAL_FIELDS)
    note = body.get("pcp_coordination_note")
    if note is not None and not isinstance(note, str):
        raise err_input(ERR_INVALID_REQUEST,
                        "pcp_coordination_note must be a string")

    a = _get_assessment_for_visit(visitId)
    if a is not None and a.get("status") != "DRAFT":
        raise err_state(ERR_ASSESSMENT_NOT_DRAFT,
                        "Only a DRAFT assessment can be updated")

    if a is None:
        a = base_fields()
        a.update({
            "visit_id": visitId,
            "member_id": v.get("member_id"),
            "medication_reconciliation": None,
            "safety_evaluation": None,
            "social_needs_screening": None,
            "pcp_coordination_note": None,
            "pcp_notified": False,
            "status": "DRAFT",
        })
        db.assessments[a["id"]] = a

    if med_rec is not None:
        a["medication_reconciliation"] = med_rec
    if safety is not None:
        a["safety_evaluation"] = safety
    if social is not None:
        a["social_needs_screening"] = social
    if note is not None:
        a["pcp_coordination_note"] = note
    touch(a)
    return success_object(serializers.assessment(a))


@bp.route("/visits/<visitId>/assessment", methods=["GET"])
def get_assessment(visitId):
    require_roles(READ_ROLES)
    _get_visit_or_404(visitId)
    a = _get_assessment_for_visit(visitId)
    items = [serializers.assessment(a)] if a is not None else []
    return success_list(items, limit=10, offset=0, total_count=len(items))


@bp.route("/visits/<visitId>/assessment/submit", methods=["POST"])
def submit_assessment(visitId):
    user_id, _ = require_roles(CLINICIAN)
    v = _get_visit_or_404(visitId)
    a = _get_assessment_for_visit(visitId)
    if a is None:
        raise err_not_found(ERR_ASSESSMENT_NOT_FOUND, "VisitAssessment")
    if a.get("status") != "DRAFT":
        raise err_state(ERR_ASSESSMENT_NOT_DRAFT,
                        "Assessment must be DRAFT to submit")
    if v.get("status") != "IN_PROGRESS":
        raise err_state(ERR_VISIT_NOT_IN_PROGRESS,
                        "Visit must be IN_PROGRESS to submit the assessment")
    _check_assigned_clinician(user_id, v)
    if not _assessment_complete(a):
        raise err_input(ERR_ASSESSMENT_INCOMPLETE,
                        "medication_reconciliation, safety_evaluation, and "
                        "social_needs_screening must all be fully populated")
    a["status"] = "SUBMITTED"
    touch(a)
    return success_object(serializers.assessment(a))


@bp.route("/visits/<visitId>/complete", methods=["POST"])
def complete_visit(visitId):
    user_id, _ = require_roles(CLINICIAN)
    v = _get_visit_or_404(visitId)
    if v.get("status") != "IN_PROGRESS":
        raise err_state(ERR_VISIT_NOT_IN_PROGRESS,
                        "Visit must be IN_PROGRESS to complete")
    _check_assigned_clinician(user_id, v)
    a = _get_assessment_for_visit(visitId)
    if a is None or a.get("status") != "SUBMITTED":
        raise err_state(ERR_ASSESSMENT_NOT_SUBMITTED,
                        "A SUBMITTED assessment is required to complete the visit")
    note = a.get("pcp_coordination_note")
    if note is None or (isinstance(note, str) and note.strip() == ""):
        raise err_input(ERR_PCP_COORDINATION_NOTE_REQUIRED,
                        "pcp_coordination_note must be non-empty at completion")

    # --- Cascade (PRD §3.5) ---
    v["status"] = "COMPLETED"
    v["actual_end"] = now_iso()
    touch(v)

    clin = db.clinicians.get(v.get("clinician_id"))
    if clin is not None:
        clin["active_daily_visit_count"] = max(
            0, int(clin.get("active_daily_visit_count") or 0) - 1)
        touch(clin)

    a["status"] = "LOCKED"

    # PCP notification per the PCP's opt-in flag
    member = db.members.get(v.get("member_id"))
    pcp = db.pcp_providers.get(member.get("pcp_provider_id")) if member else None
    if pcp is not None and pcp.get("notification_opt_in"):
        a["pcp_notified"] = True
    touch(a)

    # Recompute the member's final burden and risk tier
    if member is not None:
        final = compute_final_burden(member)
        if final is not None:
            member["burden_score_final"] = final
        refresh_member_risk(member)
        touch(member)

    m = _measurement_for_visit(v)
    if m is not None:
        m["visits_completed"] = int(m.get("visits_completed") or 0) + 1
        recompute_pcp_coordination_rate(m)
        touch(m)
        recompute_composite(m)

    return success_object(serializers.visit(v))


@bp.route("/visits/<visitId>/cancel", methods=["POST"])
def cancel_visit(visitId):
    require_roles(COORDINATOR)
    v = _get_visit_or_404(visitId)
    if v.get("status") != "SCHEDULED":
        raise err_state(ERR_VISIT_NOT_CANCELLABLE,
                        "Visit must be SCHEDULED to cancel")
    body = get_json_body()
    reason = body.get("cancellation_reason")
    if reason is None or (isinstance(reason, str) and reason.strip() == ""):
        raise err_input(ERR_CANCELLATION_REASON_REQUIRED,
                        "cancellation_reason is required")
    if reason not in CANCELLATION_REASONS:
        raise err_input(ERR_INVALID_REQUEST,
                        "Invalid cancellation_reason: %r" % reason)

    v["status"] = "CANCELLED"
    v["cancellation_reason"] = reason
    touch(v)

    clin = db.clinicians.get(v.get("clinician_id"))
    if clin is not None:
        clin["active_daily_visit_count"] = max(
            0, int(clin.get("active_daily_visit_count") or 0) - 1)
        touch(clin)

    m = _measurement_for_visit(v)
    if m is not None:
        bump_counter(m, "visits_cancelled", 1)
    return success_object(serializers.visit(v))


@bp.route("/visits/<visitId>/reschedule", methods=["POST"])
def reschedule_visit(visitId):
    require_roles(COORDINATOR)
    v = _get_visit_or_404(visitId)
    if v.get("status") != "CANCELLED":
        raise err_state(ERR_VISIT_NOT_CANCELLED,
                        "Visit must be CANCELLED to reschedule")
    body = get_json_body()
    scheduled_start_raw = require_string(body, "scheduled_start")
    scheduled_end_raw = require_string(body, "scheduled_end")
    expected_visit_version = require_int(body, "expected_visit_version")

    if int(v.get("reschedule_count") or 0) >= MAX_RESCHEDULES:
        raise err_state(ERR_MAX_RESCHEDULES_EXCEEDED,
                        "reschedule_count reached the maximum of 2")

    start = parse_ts(scheduled_start_raw, "scheduled_start")
    end = parse_ts(scheduled_end_raw, "scheduled_end")
    if not (end > start):
        raise err_input(ERR_INVALID_REQUEST,
                        "scheduled_end must be strictly later than scheduled_start")

    if _overlap_conflict(v.get("clinician_id"), start, end,
                         exclude_visit_id=v["id"]):
        raise err_state(ERR_VISIT_TIME_OVERLAP,
                        "Visit window overlaps another in-flight visit")

    enrollment = db.enrollments.get(v.get("enrollment_id"))
    if enrollment is None or enrollment.get("status") != "ACTIVE":
        raise err_state(ERR_ENROLLMENT_NOT_ACTIVE,
                        "Enrollment must be ACTIVE to reschedule")

    # OCC (rung 13; §2.5)
    if expected_visit_version != int(v.get("version") or 0):
        raise err_stale()

    v["status"] = "SCHEDULED"
    v["scheduled_start"] = fmt_ts(start)
    v["scheduled_end"] = fmt_ts(end)
    v["reschedule_count"] = int(v.get("reschedule_count") or 0) + 1
    touch(v)

    clin = db.clinicians.get(v.get("clinician_id"))
    if clin is not None:
        clin["active_daily_visit_count"] = int(
            clin.get("active_daily_visit_count") or 0) + 1
        touch(clin)

    m = _measurement_for_visit(v)
    if m is not None:
        bump_counter(m, "visits_cancelled", -1)
    return success_object(serializers.visit(v))


@bp.route("/visits/<visitId>/mark-no-show", methods=["POST"])
def mark_no_show(visitId):
    user_id, _ = require_roles(CLINICIAN)
    v = _get_visit_or_404(visitId)
    if v.get("status") != "SCHEDULED":
        raise err_state(ERR_VISIT_NOT_SCHEDULED,
                        "Visit must be SCHEDULED to mark no-show")
    _check_assigned_clinician(user_id, v)
    end = parse_ts(v.get("scheduled_end"))
    if end is None or now_clock() < end:
        raise err_state(ERR_VISIT_WINDOW_NOT_PAST,
                        "Current logical clock must be at or past scheduled_end")

    v["status"] = "NO_SHOW"
    touch(v)

    clin = db.clinicians.get(v.get("clinician_id"))
    if clin is not None:
        clin["active_daily_visit_count"] = max(
            0, int(clin.get("active_daily_visit_count") or 0) - 1)
        touch(clin)

    m = _measurement_for_visit(v)
    if m is not None:
        bump_counter(m, "visits_no_show", 1)
    return success_object(serializers.visit(v))

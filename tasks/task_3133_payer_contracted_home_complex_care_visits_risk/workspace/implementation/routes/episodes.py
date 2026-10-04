"""UrgentResponseEpisode endpoints per PRD §3.6."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_state, err_input, err_not_assigned,
                    ERR_EPISODE_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND,
                    ERR_ENROLLMENT_NOT_ACTIVE, ERR_EPISODE_NOT_TRIGGERED,
                    ERR_EPISODE_NOT_DISPATCHED, ERR_EPISODE_NOT_ON_SCENE,
                    ERR_SLA_ALREADY_LAPSED, ERR_RESOLUTION_OUTCOME_REQUIRED)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.clock import now_clock, now_iso, fmt_ts, parse_ts
from services.measurements import (get_or_create_measurement, bump_counter,
                                   recompute_composite)
from services.resources import base_fields, touch
from services.selectors import urgent_selector
from services.validation import (get_json_body, require_string, require_enum)

bp = Blueprint("episodes", __name__)

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "Clinician", "PerformanceAnalyst"]
TRIGGER_SOURCES = {"MEMBER_CALL", "PCP_ALERT", "PLAN_ALERT", "POST_ED_DISCHARGE"}
OUTCOMES = {"AVOIDED_ED", "REFERRED_TO_ED"}


def _get_episode_or_404(episode_id):
    e = db.episodes.get(episode_id)
    if e is None:
        raise err_not_found(ERR_EPISODE_NOT_FOUND, "UrgentResponseEpisode")
    return e


def _measurement_for_episode(ep):
    member = db.members.get(ep.get("member_id"))
    if member is None:
        return None
    program = db.care_programs.get(member.get("care_program_id"))
    period = int(program.get("current_period_index") or 0) if program else 0
    return get_or_create_measurement(member.get("payer_contract_id"),
                                     member["id"], period)


@bp.route("/urgent-episodes", methods=["POST"])
def create_episode():
    require_roles(["CareCoordinator", "EngagementSpecialist"])
    body = get_json_body()
    enrollment_id = require_string(body, "enrollment_id")
    trigger_source = require_enum(body, "trigger_source", TRIGGER_SOURCES)

    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err_not_found(ERR_ENROLLMENT_NOT_FOUND, "MemberEnrollment")
    if enrollment.get("status") != "ACTIVE":
        raise err_state(ERR_ENROLLMENT_NOT_ACTIVE,
                        "Enrollment must be ACTIVE to trigger an urgent episode")

    member = db.members.get(enrollment.get("member_id"))
    program = db.care_programs.get(member.get("care_program_id")) if member else None
    sla_hours = int(program.get("urgent_response_sla_hours") or 24) if program else 24

    now = now_clock()
    e = base_fields()
    e.update({
        "enrollment_id": enrollment_id,
        "member_id": enrollment.get("member_id"),
        "trigger_source": trigger_source,
        "triggered_at": fmt_ts(now),
        "sla_deadline": fmt_ts(now + timedelta(hours=sla_hours)),
        "dispatched_clinician_id": None,
        "on_scene_at": None,
        "resolved_outcome": None,
        "sla_met": None,
        "status": "TRIGGERED",
    })
    db.episodes[e["id"]] = e

    m = _measurement_for_episode(e)
    if m is not None:
        bump_counter(m, "urgent_episodes_triggered", 1)
    return success_object(serializers.episode(e), status=201)


@bp.route("/urgent-episodes", methods=["GET"])
def list_episodes():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.episodes.values())
    eid = request.args.get("enrollment_id")
    if eid:
        items = [e for e in items if e.get("enrollment_id") == eid]
    mid = request.args.get("member_id")
    if mid:
        items = [e for e in items if e.get("member_id") == mid]
    dcid = request.args.get("dispatched_clinician_id")
    if dcid:
        items = [e for e in items if e.get("dispatched_clinician_id") == dcid]
    s = request.args.get("status")
    if s:
        items = [e for e in items if e.get("status") == s]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.episode(e) for e in page],
                        limit, offset, total)


@bp.route("/urgent-episodes/<episodeId>", methods=["GET"])
def get_episode(episodeId):
    require_roles(READ_ROLES)
    e = _get_episode_or_404(episodeId)
    return success_object(serializers.episode(e))


@bp.route("/urgent-episodes/<episodeId>/dispatch", methods=["POST"])
def dispatch_episode(episodeId):
    require_roles(["CareCoordinator"])
    e = _get_episode_or_404(episodeId)
    if e.get("status") != "TRIGGERED":
        raise err_state(ERR_EPISODE_NOT_TRIGGERED,
                        "Episode must be TRIGGERED to dispatch")
    deadline = parse_ts(e.get("sla_deadline"))
    if deadline is not None and now_clock() > deadline:
        raise err_state(ERR_SLA_ALREADY_LAPSED,
                        "The SLA deadline has already passed")

    member = db.members.get(e.get("member_id"))
    program = db.care_programs.get(member.get("care_program_id")) if member else None
    clinician = urgent_selector(program)

    e["dispatched_clinician_id"] = clinician["id"]
    e["status"] = "DISPATCHED"
    touch(e)
    clinician["active_daily_visit_count"] = int(
        clinician.get("active_daily_visit_count") or 0) + 1
    touch(clinician)
    return success_object(serializers.episode(e))


@bp.route("/urgent-episodes/<episodeId>/arrive", methods=["POST"])
def arrive_episode(episodeId):
    user_id, _ = require_roles(["Clinician"])
    e = _get_episode_or_404(episodeId)
    if e.get("status") != "DISPATCHED":
        raise err_state(ERR_EPISODE_NOT_DISPATCHED,
                        "Episode must be DISPATCHED to mark arrival")
    if user_id != e.get("dispatched_clinician_id"):
        raise err_not_assigned()
    now = now_clock()
    e["status"] = "ON_SCENE"
    e["on_scene_at"] = fmt_ts(now)
    deadline = parse_ts(e.get("sla_deadline"))
    e["sla_met"] = bool(deadline is not None and now <= deadline)
    touch(e)
    return success_object(serializers.episode(e))


@bp.route("/urgent-episodes/<episodeId>/resolve", methods=["POST"])
def resolve_episode(episodeId):
    user_id, _ = require_roles(["Clinician"])
    e = _get_episode_or_404(episodeId)
    if e.get("status") != "ON_SCENE":
        raise err_state(ERR_EPISODE_NOT_ON_SCENE,
                        "Episode must be ON_SCENE to resolve")
    body = get_json_body()
    outcome = body.get("resolved_outcome")
    if outcome is None or (isinstance(outcome, str) and outcome.strip() == ""):
        raise err_input(ERR_RESOLUTION_OUTCOME_REQUIRED,
                        "resolved_outcome is required")
    if outcome not in OUTCOMES:
        from errors import ERR_INVALID_REQUEST
        raise err_input(ERR_INVALID_REQUEST,
                        "Invalid resolved_outcome: %r" % outcome)
    if user_id != e.get("dispatched_clinician_id"):
        raise err_not_assigned()

    e["status"] = "RESOLVED"
    e["resolved_outcome"] = outcome
    touch(e)

    clin = db.clinicians.get(e.get("dispatched_clinician_id"))
    if clin is not None:
        clin["active_daily_visit_count"] = max(
            0, int(clin.get("active_daily_visit_count") or 0) - 1)
        touch(clin)

    m = _measurement_for_episode(e)
    if m is not None:
        if outcome == "AVOIDED_ED":
            m["urgent_episodes_avoided_ed"] = int(
                m.get("urgent_episodes_avoided_ed") or 0) + 1
        if e.get("sla_met"):
            m["urgent_episodes_sla_met"] = int(
                m.get("urgent_episodes_sla_met") or 0) + 1
        touch(m)
        recompute_composite(m)

    # REFERRED_TO_ED cascade: create a POST_ED_FOLLOWUP visit (PRD §3.6)
    if outcome == "REFERRED_TO_ED":
        enrollment = db.enrollments.get(e.get("enrollment_id"))
        team = None
        if enrollment is not None:
            for t in db.care_teams.values():
                if t.get("enrollment_id") == enrollment["id"]:
                    team = t
                    break
        primary_np_id = team.get("primary_np_id") if team else None
        now = now_clock()
        v = base_fields()
        v.update({
            "enrollment_id": e.get("enrollment_id"),
            "member_id": e.get("member_id"),
            "clinician_id": primary_np_id,
            "visit_type": "POST_ED_FOLLOWUP",
            "scheduled_start": fmt_ts(now),
            "scheduled_end": fmt_ts(now + timedelta(hours=72)),
            "actual_start": None,
            "actual_end": None,
            "cancellation_reason": None,
            "reschedule_count": 0,
            "status": "SCHEDULED",
        })
        db.visits[v["id"]] = v
        if primary_np_id:
            np_clin = db.clinicians.get(primary_np_id)
            if np_clin is not None:
                np_clin["active_daily_visit_count"] = int(
                    np_clin.get("active_daily_visit_count") or 0) + 1
                touch(np_clin)

    return success_object(serializers.episode(e))

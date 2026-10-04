"""Volunteers and event enrollments (PRD 3.6)."""
from flask import Blueprint, request

from db import STORES, new_record
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_str, opt_bool,
    opt_array, raise_err, now_iso, parse_date, clock_date, parse_dt,
    TRADE_VALUES,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_NOT_OWNER, E_FORBIDDEN,
    E_VOLUNTEER_NOT_FOUND, E_EVENT_NOT_FOUND, E_ENROLLMENT_NOT_FOUND,
    E_EVENT_NOT_PUBLISHED, E_VOLUNTEER_NOT_ELIGIBLE, E_EVENT_AT_CAPACITY,
    E_TEAM_LEADER_ASSIGNED, E_VOLUNTEER_DOUBLE_BOOKED,
)
from logic import (
    bump, is_eligible, event_enrollments, active_enrollment_count,
    get_event, get_volunteer, ACTIVE_ENROLLMENT_STATES,
)
from cascades import deactivate_volunteer_cascade
from serializers import ser_volunteer, ser_enrollment

bp = Blueprint("volunteers", __name__)

VOLUNTEER_STATUSES = ("REGISTERED", "DEACTIVATED")
ENROLLMENT_STATUSES = ("ENROLLED", "CONFIRMED", "CHECKED_IN", "COMPLETED",
                       "NO_SHOW", "WITHDRAWN")


@bp.post("/rebuild/volunteers")
def create_volunteer():
    require_roles("Anonymous")
    b = body()
    skills = opt_array(b, "skills", default=[])
    for s in skills:
        if s not in TRADE_VALUES:
            raise_err(E_INVALID_REQUEST, 400,
                      "skills entries must be one of "
                      + ", ".join(TRADE_VALUES))
    rec = new_record("volunteers", {
        "full_name": req_str(b, "full_name"),
        "email": req_str(b, "email"),
        "skills": list(skills),
        "team_leader_eligible": opt_bool(b, "team_leader_eligible", False),
        "waiver_signed_on": None,
        "safety_training_completed_on": None,
        "status": "REGISTERED",
    }, now_iso)
    return ok_obj(ser_volunteer(rec), 201)


@bp.get("/rebuild/volunteers/<volunteerId>")
def get_volunteer_route(volunteerId):
    require_roles("Any")
    rec = get_or_404("volunteers", volunteerId, E_VOLUNTEER_NOT_FOUND)
    return ok_obj(ser_volunteer(rec))


def _opt_date_field(b, key):
    if key not in b:
        return None, False
    v = b[key]
    if v is None:
        return None, True
    if parse_dt(v) is None:
        raise_err(E_INVALID_REQUEST, 400,
                  "%s must be an ISO-8601 date" % key)
    return v, True


@bp.patch("/rebuild/volunteers/<volunteerId>")
def patch_volunteer(volunteerId):
    uid, role = require_roles("Volunteer", "AffiliateStaff")
    b = body()
    # Tier 3: ownership and role-field rules.
    if role == "Volunteer":
        if uid != volunteerId:
            raise_err(E_NOT_OWNER, 403,
                      "a Volunteer may modify only its own record")
        if "safety_training_completed_on" in b or "status" in b:
            raise_err(E_FORBIDDEN, 403,
                      "a Volunteer may only set waiver_signed_on")
    if role == "AffiliateStaff" and "waiver_signed_on" in b:
        raise_err(E_FORBIDDEN, 403,
                  "the waiver is self-service; staff may not set "
                  "waiver_signed_on")
    rec = get_or_404("volunteers", volunteerId, E_VOLUNTEER_NOT_FOUND)
    touched = False
    waiver, waiver_set = _opt_date_field(b, "waiver_signed_on")
    if waiver_set:
        rec["waiver_signed_on"] = waiver
        touched = True
    training, training_set = _opt_date_field(b, "safety_training_completed_on")
    if training_set:
        rec["safety_training_completed_on"] = training
        touched = True
    if "status" in b and b["status"] is not None:
        target = b["status"]
        if not isinstance(target, str) or target not in VOLUNTEER_STATUSES:
            raise_err(E_INVALID_REQUEST, 400,
                      "status must be REGISTERED or DEACTIVATED")
        if target == rec["status"]:
            raise_err(E_INVALID_STATE, 409,
                      "volunteer is already %s" % target)
        if target == "DEACTIVATED":
            rec["status"] = "DEACTIVATED"
            touched = True
            deactivate_volunteer_cascade(rec["id"])
        else:
            rec["status"] = "REGISTERED"
            touched = True
    if not touched:
        raise_err(E_INVALID_REQUEST, 400, "no updatable field provided")
    bump(rec)
    return ok_obj(ser_volunteer(rec))


def _double_booked(volunteer_id, event, exclude_enrollment_id=None):
    """Active enrollment on ANOTHER event sharing the same calendar date."""
    target_day = parse_date(event["event_date"])
    for e in STORES["enrollments"].values():
        if e["volunteer_id"] != volunteer_id:
            continue
        if e["status"] not in ACTIVE_ENROLLMENT_STATES:
            continue
        if exclude_enrollment_id and e["id"] == exclude_enrollment_id:
            continue
        other = get_event(e["event_id"])
        if other is None or other["id"] == event["id"]:
            continue
        if parse_date(other["event_date"]) == target_day:
            return True
    return False


def _enrollment_gauntlet(event, volunteer, is_leader):
    """Shared creation/re-enrollment checks (state, eligibility, temporal,
    constraint), in PRD 2.10 tier order."""
    if event["status"] != "PUBLISHED":
        raise_err(E_EVENT_NOT_PUBLISHED, 409,
                  "the event is not open for enrollment")
    if not is_eligible(volunteer):
        raise_err(E_VOLUNTEER_NOT_ELIGIBLE, 409,
                  "the volunteer is not eligible")
    if _double_booked(volunteer["id"], event):
        raise_err(E_VOLUNTEER_DOUBLE_BOOKED, 409,
                  "the volunteer already holds an active enrollment on "
                  "another event that day")
    if active_enrollment_count(event["id"]) >= event["max_volunteers"]:
        raise_err(E_EVENT_AT_CAPACITY, 409, "the event is at capacity")
    if is_leader:
        if not volunteer["team_leader_eligible"]:
            raise_err(E_INVALID_REQUEST, 400,
                      "the volunteer is not team-leader eligible")
        assigned = any(
            e["is_team_leader"]
            and e["status"] in ACTIVE_ENROLLMENT_STATES
            for e in event_enrollments(event["id"]))
        if assigned:
            raise_err(E_TEAM_LEADER_ASSIGNED, 409,
                      "the event already has an active team leader")


@bp.post("/rebuild/enrollments")
def create_enrollment():
    uid, role = require_roles("Volunteer", "AffiliateStaff")
    b = body()
    volunteer_id = b.get("volunteer_id")
    # Tier 3: a Volunteer may only enroll itself.
    if role == "Volunteer":
        if volunteer_id is None:
            raise_err(E_INVALID_REQUEST, 400, "volunteer_id is required")
        if volunteer_id != uid:
            raise_err(E_NOT_OWNER, 403,
                      "a Volunteer may only enroll itself")
    event_id = b.get("event_id")
    if event_id is None:
        raise_err(E_INVALID_REQUEST, 400, "event_id is required")
    event = get_or_404("events", event_id, E_EVENT_NOT_FOUND)
    if volunteer_id is None:
        raise_err(E_INVALID_REQUEST, 400, "volunteer_id is required")
    volunteer = get_or_404("volunteers", volunteer_id, E_VOLUNTEER_NOT_FOUND)
    is_leader = opt_bool(b, "is_team_leader", False)
    _enrollment_gauntlet(event, volunteer, is_leader)
    rec = new_record("enrollments", {
        "event_id": event_id,
        "volunteer_id": volunteer_id,
        "is_team_leader": is_leader,
        "status": "ENROLLED",
    }, now_iso)
    return ok_obj(ser_enrollment(rec), 201)


@bp.get("/rebuild/enrollments")
def list_enrollments():
    require_roles("Any")
    recs = list(STORES["enrollments"].values())
    ev = request.args.get("event_id")
    if ev is not None:
        recs = [r for r in recs if r["event_id"] == ev]
    vid = request.args.get("volunteer_id")
    if vid is not None:
        recs = [r for r in recs if r["volunteer_id"] == vid]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_enrollment)


@bp.get("/rebuild/enrollments/<enrollmentId>")
def get_enrollment(enrollmentId):
    require_roles("Any")
    rec = get_or_404("enrollments", enrollmentId, E_ENROLLMENT_NOT_FOUND)
    return ok_obj(ser_enrollment(rec))


def _actor_is_team_leader(uid, event_id):
    return any(
        e["volunteer_id"] == uid and e["is_team_leader"]
        and e["status"] in ACTIVE_ENROLLMENT_STATES
        for e in event_enrollments(event_id))


@bp.patch("/rebuild/enrollments/<enrollmentId>")
def patch_enrollment(enrollmentId):
    uid, role = require_roles("Volunteer", "AffiliateStaff")
    rec = get_or_404("enrollments", enrollmentId, E_ENROLLMENT_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in ENROLLMENT_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(ENROLLMENT_STATUSES))

    # Tier 3: ownership / role-field rules per target.
    if role == "Volunteer":
        if target in ("WITHDRAWN", "ENROLLED"):
            if rec["volunteer_id"] != uid:
                raise_err(E_NOT_OWNER, 403,
                          "a Volunteer may only modify its own enrollment")
        elif target == "CHECKED_IN":
            if not _actor_is_team_leader(uid, rec["event_id"]):
                raise_err(E_NOT_OWNER, 403,
                          "check-in requires staff or the event's team "
                          "leader")
        elif target == "NO_SHOW":
            raise_err(E_FORBIDDEN, 403,
                      "only staff may mark an enrollment NO_SHOW")
        else:
            raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)

    if target == "WITHDRAWN":
        if rec["status"] not in ("ENROLLED", "CONFIRMED"):
            raise_err(E_INVALID_STATE, 409,
                      "only ENROLLED or CONFIRMED enrollments can be "
                      "withdrawn")
        rec["status"] = "WITHDRAWN"
    elif target == "ENROLLED":
        # Re-enrollment re-runs the creation gauntlet.
        if rec["status"] != "WITHDRAWN":
            raise_err(E_INVALID_STATE, 409,
                      "only a WITHDRAWN enrollment can re-enroll")
        event = get_event(rec["event_id"])
        volunteer = get_volunteer(rec["volunteer_id"])
        if event["status"] != "PUBLISHED":
            raise_err(E_EVENT_NOT_PUBLISHED, 409,
                      "the event is not open for enrollment")
        if not is_eligible(volunteer):
            raise_err(E_VOLUNTEER_NOT_ELIGIBLE, 409,
                      "the volunteer is not eligible")
        if _double_booked(rec["volunteer_id"], event,
                          exclude_enrollment_id=rec["id"]):
            raise_err(E_VOLUNTEER_DOUBLE_BOOKED, 409,
                      "the volunteer already holds an active enrollment on "
                      "another event that day")
        if active_enrollment_count(event["id"]) >= event["max_volunteers"]:
            raise_err(E_EVENT_AT_CAPACITY, 409, "the event is at capacity")
        rec["status"] = "ENROLLED"
    elif target == "CHECKED_IN":
        if rec["status"] != "CONFIRMED":
            raise_err(E_INVALID_STATE, 409,
                      "only a CONFIRMED enrollment can check in")
        event = get_event(rec["event_id"])
        if parse_date(event["event_date"]) != clock_date():
            raise_err(E_INVALID_STATE, 409,
                      "check-in is only possible on the event day")
        rec["status"] = "CHECKED_IN"
    elif target == "NO_SHOW":
        if rec["status"] != "CONFIRMED":
            raise_err(E_INVALID_STATE, 409,
                      "only a CONFIRMED enrollment can be marked NO_SHOW")
        rec["status"] = "NO_SHOW"
    else:
        # CONFIRMED / COMPLETED are system-driven.
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    bump(rec)
    return ok_obj(ser_enrollment(rec))

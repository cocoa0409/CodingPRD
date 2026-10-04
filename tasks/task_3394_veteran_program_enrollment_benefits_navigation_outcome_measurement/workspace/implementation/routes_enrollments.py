"""Routes: enrollments, assessments, enrollment transitions, enrollment surveys."""
from flask import Blueprint, request

import db
import services
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object, ok_list
from validation import (
    get_body, req_str, opt_str, req_enum, req_int, opt_bool, pagination_params,
)

bp = Blueprint("enrollments", __name__)

ENROLLMENT_TARGETS = ("SUSPENDED", "ACTIVE", "COMPLETED", "WITHDRAWN")


@bp.post("/veteran-services/enrollments")
def create_enrollment():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    program_track_id = req_str(body, "program_track_id")
    coordination_consent = opt_bool(body, "coordination_consent", False)
    require_role(role, ["IntakeCoordinator"])
    # Existence: body FKs in declared input order (member_id, then program_track_id)
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    track = db.STORE["program_tracks"].get(program_track_id)
    if track is None:
        raise ApiError("ERR_PROGRAM_TRACK_NOT_FOUND", "program track does not exist", 404)
    # Priority 7: member must be VERIFIED
    if member["verification_status"] != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED", "member is not VERIFIED", 409)
    # Priority 10: duplication avoidance against the track's category
    if not coordination_consent and services.has_active_external_record(member_id, track["track_code"]):
        raise ApiError("ERR_EXTERNAL_SERVICE_CONFLICT",
                       "an ACTIVE external service record covers this service category", 409)
    # Priority 13: track capacity (inclusive-full boundary)
    if track["active_enrollment_count"] >= track["capacity"]:
        raise ApiError("ERR_TRACK_CAPACITY_REACHED", "program track is at capacity", 409)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "program_track_id": program_track_id,
        "status": "INTAKE", "intensity_tier": None, "latest_acuity_score": None,
        "coordination_consent": coordination_consent,
        "exit_disposition": None, "exit_reason": None, "exit_at": None,
    }
    services.stamp_new(rec)
    db.STORE["enrollments"][rec["id"]] = rec
    track["active_enrollment_count"] += 1
    services.bump(track)
    services.schedule_baseline_survey(rec)
    services.refresh_engagement(member_id, always_bump=True)
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/enrollments")
def list_enrollments():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["IntakeCoordinator", "CareerCounselor", "OutcomeAnalyst"])
    member_id = request.args.get("member_id")
    track_id = request.args.get("program_track_id")
    status = request.args.get("status")
    items = [e for e in db.STORE["enrollments"].values()
             if (member_id is None or e["member_id"] == member_id)
             and (track_id is None or e["program_track_id"] == track_id)
             and (status is None or e["status"] == status)]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(e) for e in page], limit, offset, total)


@bp.get("/veteran-services/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    uid, role = authenticate()
    require_role(role, ["IntakeCoordinator", "CareerCounselor", "OutcomeAnalyst"])
    rec = db.STORE["enrollments"].get(enrollment_id)
    if rec is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "enrollment does not exist", 404)
    return ok_object(services.serialize(rec))


@bp.post("/veteran-services/enrollments/<enrollment_id>/assessments")
def create_assessment(enrollment_id):
    uid, role = authenticate()
    body = get_body()
    psych = req_int(body, "psych_score", minimum=0, maximum=10)
    phys = req_int(body, "phys_score", minimum=0, maximum=10)
    voc = req_int(body, "voc_score", minimum=0, maximum=10)
    soc = req_int(body, "soc_score", minimum=0, maximum=10)
    notes = opt_str(body, "notes")
    require_role(role, ["IntakeCoordinator"])
    enrollment = db.STORE["enrollments"].get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "enrollment does not exist", 404)
    if enrollment["status"] not in ("INTAKE", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE",
                       "assessments are not allowed on a terminal enrollment", 409)
    member = db.STORE["members"].get(enrollment["member_id"])
    score, tier = services.compute_acuity(member["member_type"], psych, phys, voc, soc)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "enrollment_id": enrollment_id,
        "psych_score": psych, "phys_score": phys, "voc_score": voc, "soc_score": soc,
        "notes": notes, "acuity_score": score, "tier_result": tier,
    }
    services.stamp_new(rec, lean=True)  # Assessment: id + created_at only
    db.STORE["assessments"][rec["id"]] = rec
    enrollment["intensity_tier"] = tier
    enrollment["latest_acuity_score"] = score
    if enrollment["status"] == "INTAKE":
        enrollment["status"] = "ACTIVE"
    services.bump(enrollment)
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/enrollments/<enrollment_id>/assessments")
def list_assessments(enrollment_id):
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["IntakeCoordinator", "OutcomeAnalyst"])
    enrollment = db.STORE["enrollments"].get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "enrollment does not exist", 404)
    items = [a for a in db.STORE["assessments"].values()
             if a["enrollment_id"] == enrollment_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(a) for a in page], limit, offset, total)


@bp.post("/veteran-services/enrollments/<enrollment_id>/transition")
def transition_enrollment(enrollment_id):
    uid, role = authenticate()
    body = get_body()
    target = req_enum(body, "target_status", ENROLLMENT_TARGETS)
    exit_reason = opt_str(body, "exit_reason")
    require_role(role, ["IntakeCoordinator"])
    enrollment = db.STORE["enrollments"].get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "enrollment does not exist", 404)
    if target == "SUSPENDED":
        if enrollment["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "enrollment is not ACTIVE", 409)
        enrollment["status"] = "SUSPENDED"
        services.bump(enrollment)
        return ok_object(services.serialize(enrollment))
    if target == "ACTIVE":
        if enrollment["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "enrollment is not SUSPENDED", 409)
        enrollment["status"] = "ACTIVE"
        services.bump(enrollment)
        return ok_object(services.serialize(enrollment))
    # Exits
    if target == "COMPLETED":
        if enrollment["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "enrollment is not ACTIVE", 409)
        disposition = "COMPLETED"
    else:  # WITHDRAWN
        if enrollment["status"] not in ("INTAKE", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE",
                           "enrollment cannot be withdrawn from its current state", 409)
        disposition = "WITHDRAWN"
    enrollment["status"] = disposition
    enrollment["exit_disposition"] = disposition
    enrollment["exit_at"] = db.now()
    enrollment["exit_reason"] = exit_reason
    services.bump(enrollment)
    track = db.STORE["program_tracks"].get(enrollment["program_track_id"])
    if track is not None and track["active_enrollment_count"] > 0:
        track["active_enrollment_count"] -= 1
        services.bump(track)
    if disposition == "COMPLETED":
        services.schedule_exit_surveys(enrollment)
    # WITHDRAWN creates no surveys
    services.refresh_engagement(enrollment["member_id"])
    return ok_object(services.serialize(enrollment))


@bp.get("/veteran-services/enrollments/<enrollment_id>/surveys")
def list_enrollment_surveys(enrollment_id):
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["IntakeCoordinator", "OutcomeAnalyst"])
    enrollment = db.STORE["enrollments"].get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "enrollment does not exist", 404)
    wave = request.args.get("wave")
    items = [s for s in db.STORE["surveys"].values()
             if s["enrollment_id"] == enrollment_id and (wave is None or s["wave"] == wave)]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(s) for s in page], limit, offset, total)

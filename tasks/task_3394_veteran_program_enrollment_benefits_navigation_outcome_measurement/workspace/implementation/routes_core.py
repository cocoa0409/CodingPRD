"""Routes: logical clock, program tracks, members, eligibility cases,
external service records."""
from flask import Blueprint, request

import db
import services
from constants import (
    TRACK_CODES, MEMBER_TYPES, SERVICE_ERAS, INJURY_CONNECTIONS, BRANCHES,
    SERVICE_CATEGORIES,
)
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object, ok_list
from validation import (
    get_body, req_str, opt_str, req_enum, opt_enum, req_int, req_dt, opt_dt,
    pagination_params,
)

bp = Blueprint("core", __name__)

CASE_TARGETS = ("PENDED", "UNDER_REVIEW", "VERIFIED", "DENIED")


@bp.post("/veteran-services/_clock/set_current_utc")
def set_current_utc():
    uid, role = authenticate()
    body = get_body()
    to = req_dt(body, "to_iso8601")
    require_role(role, ["PlatformAdmin"])
    db.set_clock(to)
    services.run_clock_sweep()
    return ok_object({"current_utc": db.iso(db.now())})


# ---------------------------------------------------------------------------
# Program tracks
# ---------------------------------------------------------------------------

@bp.post("/veteran-services/program-tracks")
def create_program_track():
    uid, role = authenticate()
    body = get_body()
    track_code = req_enum(body, "track_code", TRACK_CODES)
    name = req_str(body, "name")
    capacity = req_int(body, "capacity", minimum=1)
    require_role(role, ["PlatformAdmin"])
    for t in db.STORE["program_tracks"].values():
        if t["track_code"] == track_code:
            raise ApiError("ERR_DUPLICATE_TRACK_CODE", "track_code is already in use", 409)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "track_code": track_code, "name": name, "capacity": capacity,
        "active_enrollment_count": 0,
    }
    services.stamp_new(rec)
    db.STORE["program_tracks"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/program-tracks")
def list_program_tracks():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "CareerCounselor", "OutcomeAnalyst"])
    code = request.args.get("track_code")
    items = [t for t in db.STORE["program_tracks"].values()
             if code is None or t["track_code"] == code]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(t) for t in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@bp.post("/veteran-services/members")
def create_member():
    uid, role = authenticate()
    body = get_body()
    full_name = req_str(body, "full_name")
    member_type = req_enum(body, "member_type", MEMBER_TYPES)
    service_era = req_enum(body, "service_era_claimed", SERVICE_ERAS)
    injury = req_enum(body, "injury_connection_claimed", INJURY_CONNECTIONS)
    branch = opt_enum(body, "branch_of_service", BRANCHES)
    if member_type == "FAMILY_SUPPORT" and branch is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "branch_of_service must be null for FAMILY_SUPPORT members", 400)
    require_role(role, ["IntakeCoordinator"])
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "full_name": full_name, "member_type": member_type,
        "branch_of_service": branch,
        "service_era_claimed": service_era,
        "injury_connection_claimed": injury,
        "verification_status": "UNVERIFIED",
        "verified_service_era": None,
        "verified_injury_connection": None,
        "engagement_status": "INACTIVE",
        "total_monthly_compensation_cents": 0,
    }
    services.stamp_new(rec)
    db.STORE["members"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/members/<member_id>")
def get_member(member_id):
    uid, role = authenticate()
    require_role(role, ["IntakeCoordinator", "OutcomeAnalyst", "AccreditedRepresentative",
                        "BenefitsOfficer", "CareerCounselor", "EventCoordinator",
                        "ProgramMember"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    if role == "ProgramMember" and member["id"] != uid:
        raise ApiError("ERR_RESOURCE_NOT_OWNED", "members may only read their own record", 403)
    return ok_object(services.serialize(member))


# ---------------------------------------------------------------------------
# Eligibility cases
# ---------------------------------------------------------------------------

@bp.post("/veteran-services/eligibility-cases")
def create_eligibility_case():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    expected = req_int(body, "expected_member_version")
    require_role(role, ["IntakeCoordinator"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    if expected != member["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_member_version does not match the member's current version", 412)
    for c in db.STORE["eligibility_cases"].values():
        if c["member_id"] == member_id and c["status"] in ("UNDER_REVIEW", "PENDED"):
            c["status"] = "SUPERSEDED"
            services.bump(c)
    services.bump(member)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "status": "UNDER_REVIEW",
        "pend_reason": None, "denial_reason": None, "decided_at": None,
    }
    services.stamp_new(rec)
    db.STORE["eligibility_cases"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/members/<member_id>/eligibility-cases")
def list_eligibility_cases(member_id):
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["IntakeCoordinator", "ProgramMember"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    if role == "ProgramMember" and member["id"] != uid:
        raise ApiError("ERR_RESOURCE_NOT_OWNED", "members may only list their own cases", 403)
    status = request.args.get("status")
    items = [c for c in db.STORE["eligibility_cases"].values()
             if c["member_id"] == member_id and (status is None or c["status"] == status)]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(c) for c in page], limit, offset, total)


@bp.post("/veteran-services/eligibility-cases/<case_id>/transition")
def transition_eligibility_case(case_id):
    uid, role = authenticate()
    body = get_body()
    target = req_enum(body, "target_status", CASE_TARGETS)
    pend_reason = opt_str(body, "pend_reason")
    denial_reason = opt_str(body, "denial_reason")
    verified_service_era = None
    verified_injury_connection = None
    if target == "VERIFIED":
        verified_service_era = req_enum(body, "verified_service_era", SERVICE_ERAS)
        verified_injury_connection = req_enum(body, "verified_injury_connection",
                                              INJURY_CONNECTIONS)
    require_role(role, ["IntakeCoordinator"])
    case = db.STORE["eligibility_cases"].get(case_id)
    if case is None:
        raise ApiError("ERR_ELIGIBILITY_CASE_NOT_FOUND", "eligibility case does not exist", 404)
    if target == "PENDED":
        if case["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "case is not UNDER_REVIEW", 409)
        case["status"] = "PENDED"
        case["pend_reason"] = pend_reason
    elif target == "UNDER_REVIEW":
        if case["status"] != "PENDED":
            raise ApiError("ERR_INVALID_STATE", "case is not PENDED", 409)
        case["status"] = "UNDER_REVIEW"
    elif target == "DENIED":
        if case["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "case is not UNDER_REVIEW", 409)
        case["status"] = "DENIED"
        case["denial_reason"] = denial_reason
        case["decided_at"] = db.now()
    else:  # VERIFIED
        if case["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "case is not UNDER_REVIEW", 409)
        member = db.STORE["members"].get(case["member_id"])
        if not (verified_service_era == "POST_911"
                and (member["member_type"] == "FAMILY_SUPPORT"
                     or verified_injury_connection == "SERVICE_CONNECTED")):
            raise ApiError("ERR_ELIGIBILITY_CRITERIA_NOT_MET",
                           "the eligibility policy is not satisfied", 409)
        case["status"] = "VERIFIED"
        case["decided_at"] = db.now()
        member["verification_status"] = "VERIFIED"
        member["verified_service_era"] = verified_service_era
        member["verified_injury_connection"] = verified_injury_connection
        services.bump(member)
    services.bump(case)
    return ok_object(services.serialize(case))


# ---------------------------------------------------------------------------
# External service records
# ---------------------------------------------------------------------------

@bp.post("/veteran-services/external-service-records")
def create_external_service_record():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    organization_name = req_str(body, "organization_name")
    service_category = req_enum(body, "service_category", SERVICE_CATEGORIES)
    start_date = req_dt(body, "start_date")
    end_date = opt_dt(body, "end_date")
    require_role(role, ["IntakeCoordinator"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "organization_name": organization_name,
        "service_category": service_category, "start_date": start_date,
        "end_date": end_date, "status": "ACTIVE",
    }
    services.stamp_new(rec)
    db.STORE["external_service_records"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/members/<member_id>/external-service-records")
def list_external_service_records(member_id):
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["IntakeCoordinator"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    status = request.args.get("status")
    category = request.args.get("service_category")
    items = [x for x in db.STORE["external_service_records"].values()
             if x["member_id"] == member_id
             and (status is None or x["status"] == status)
             and (category is None or x["service_category"] == category)]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(x) for x in page], limit, offset, total)

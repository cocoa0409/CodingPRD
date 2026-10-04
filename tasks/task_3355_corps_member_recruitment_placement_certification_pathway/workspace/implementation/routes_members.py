"""Corps members, the pre-service institute and the member sub-collections."""

from flask import Blueprint, request

import serialize
import services
import validation
from envelope import ok, paginate, read_json, require_auth, sorted_by_created
from errors import ApiError
from store import MEMBERS, MILESTONES, PLACEMENTS, SUPPORT_RECORDS, now, touch
from util import iso

bp = Blueprint("members", __name__)

PRACTICE_CEILING = 480
PRACTICE_FLOOR = 120


def _load_member(member_id):
    member = MEMBERS.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    return member


@bp.route("/corps/corps-members", methods=["GET"])
def list_members():
    require_auth(["PlacementCoordinator", "InstituteDirector", "CertificationOfficer"])
    application_id = request.args.get("application_id")
    rows = sorted_by_created(MEMBERS.values())
    if application_id:
        rows = [r for r in rows if r["application_id"] == application_id]
    page, window = paginate(rows)
    return ok([serialize.member(r) for r in page], 200, page=window)


@bp.route("/corps/corps-members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_auth(["PlacementCoordinator", "InstituteDirector", "CertificationOfficer"])
    return ok(serialize.member(_load_member(member_id)), 200)


# --------------------------------------------------------------------------
# Service dimension: leave, return, exit
# --------------------------------------------------------------------------
@bp.route("/corps/corps-members/<member_id>/leave", methods=["POST"])
def place_on_leave(member_id):
    require_auth(["PlacementCoordinator"])
    read_json()
    member = _load_member(member_id)
    if member["service_status"] == "EXITED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if member["service_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only a member in ACTIVE service can go on leave.")
    member["service_status"] = "ON_LEAVE"
    member["leave_started_at"] = iso(now())
    touch(member)
    services.refresh_member_placements(member)
    return ok(serialize.member(member), 200)


@bp.route("/corps/corps-members/<member_id>/return-from-leave", methods=["POST"])
def return_from_leave(member_id):
    require_auth(["PlacementCoordinator"])
    read_json()
    member = _load_member(member_id)
    if member["service_status"] != "ON_LEAVE":
        raise ApiError("ERR_INVALID_STATE", "Only a member on leave can return to active service.")
    member["service_status"] = "ACTIVE"
    member["leave_started_at"] = None
    member["service_started_at"] = iso(now())
    touch(member)
    services.refresh_member_placements(member)
    return ok(serialize.member(member), 200)


@bp.route("/corps/corps-members/<member_id>/exit", methods=["POST"])
def exit_member(member_id):
    require_auth(["PlacementCoordinator"])
    body = read_json()
    exit_reason = validation.string(body, "exit_reason")
    member = _load_member(member_id)
    if member["service_status"] == "EXITED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if member["service_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only a member in ACTIVE service can exit the corps.")
    member["service_status"] = "EXITED"
    member["exit_reason"] = exit_reason
    touch(member)
    services.refresh_member_placements(member)
    return ok(serialize.member(member), 200)


# --------------------------------------------------------------------------
# Institute dimension
# --------------------------------------------------------------------------
@bp.route("/corps/corps-members/<member_id>/institute/practice-hours", methods=["POST"])
def record_practice_hours(member_id):
    require_auth(["InstituteDirector"])
    body = read_json()
    delta = validation.integer(body, "practice_hours_delta", minimum=0)
    member = _load_member(member_id)
    if member["institute_status"] not in ("ENROLLED", "IN_TRAINING"):
        raise ApiError("ERR_INVALID_STATE", "The pre-service institute is already complete.")
    if member["practice_teaching_hours"] + delta > PRACTICE_CEILING:
        raise ApiError("ERR_PRACTICE_HOURS_EXCEEDED")
    member["institute_status"] = "IN_TRAINING"
    member["practice_teaching_hours"] = member["practice_teaching_hours"] + delta
    services.refresh_member(member)
    return ok(serialize.member(member), 200)


@bp.route("/corps/corps-members/<member_id>/institute/complete", methods=["POST"])
def complete_institute(member_id):
    require_auth(["InstituteDirector"])
    read_json()
    member = _load_member(member_id)
    if member["institute_status"] != "IN_TRAINING":
        raise ApiError("ERR_INVALID_STATE", "Only a member in training can complete the institute.")
    if member["practice_teaching_hours"] < PRACTICE_FLOOR:
        raise ApiError("ERR_INVALID_STATE", "The practice-teaching floor has not been reached.")
    member["institute_status"] = "COMPLETED"
    services.refresh_member(member)
    services.refresh_member_placements(member)
    return ok(serialize.member(member), 200)


# --------------------------------------------------------------------------
# Member sub-collections
# --------------------------------------------------------------------------
@bp.route("/corps/corps-members/<member_id>/placements", methods=["GET"])
def list_member_placements(member_id):
    require_auth(["PlacementCoordinator", "CertificationOfficer"])
    _load_member(member_id)
    rows = [p for p in sorted_by_created(PLACEMENTS.values()) if p["corps_member_id"] == member_id]
    page, window = paginate(rows)
    return ok([serialize.placement(p) for p in page], 200, page=window)


@bp.route("/corps/corps-members/<member_id>/certification-milestones", methods=["GET"])
def list_member_milestones(member_id):
    require_auth(["PlacementCoordinator", "CertificationOfficer"])
    _load_member(member_id)
    rows = [m for m in MILESTONES.values() if m["corps_member_id"] == member_id]
    ordered = services.order_member_milestones(rows)
    page, window = paginate(ordered)
    return ok([serialize.milestone(m) for m in page], 200, page=window)


@bp.route("/corps/corps-members/<member_id>/support-records", methods=["GET"])
def list_member_support_records(member_id):
    require_auth(["PlacementCoordinator", "CertificationOfficer", "Coach"])
    _load_member(member_id)
    rows = [
        r for r in sorted_by_created(SUPPORT_RECORDS.values()) if r["corps_member_id"] == member_id
    ]
    page, window = paginate(rows)
    return ok([serialize.support_record(r) for r in page], 200, page=window)

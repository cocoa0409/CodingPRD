"""Certification pathways and the two-dimensional certification milestone machine."""

from flask import Blueprint, request

import serialize
import services
import validation
from envelope import ok, paginate, read_json, require_auth, sorted_by_created
from errors import ApiError
from store import APPLICATIONS, MEMBERS, MILESTONES, PATHWAYS, REGIONS, now, stamp, touch
from util import dt_date, iso

bp = Blueprint("certification", __name__)


def _load_milestone(milestone_id):
    milestone = MILESTONES.get(milestone_id)
    if milestone is None:
        raise ApiError("ERR_MILESTONE_NOT_FOUND")
    return milestone


def _owning_member(milestone):
    member = MEMBERS.get(milestone["corps_member_id"])
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    return member


# --------------------------------------------------------------------------
# Certification pathways
# --------------------------------------------------------------------------
@bp.route("/corps/certification-pathways", methods=["POST"])
def create_pathway():
    require_auth(["PlatformAdmin"])
    body = read_json()
    validation.require(
        body,
        "region_id",
        "state_code",
        "certification_track",
        "required_coursework_hours",
        "required_practice_hours",
        "deadline_days_before_term",
        "coursework_fee_cents",
    )
    region_id = validation.string(body, "region_id")
    state_code = validation.state_code(body, "state_code")
    track = validation.enum(body, "certification_track", validation.CERTIFICATION_TRACKS)
    coursework_hours = validation.integer(body, "required_coursework_hours", minimum=1)
    practice_hours = validation.integer(body, "required_practice_hours", minimum=1)
    deadline_days = validation.integer(body, "deadline_days_before_term", minimum=0)
    coursework_fee = validation.integer(body, "coursework_fee_cents", minimum=0)
    if region_id not in REGIONS:
        raise ApiError("ERR_REGION_NOT_FOUND")
    record = {
        "region_id": region_id,
        "state_code": state_code,
        "certification_track": track,
        "required_coursework_hours": coursework_hours,
        "required_practice_hours": practice_hours,
        "deadline_days_before_term": deadline_days,
        "coursework_fee_cents": coursework_fee,
    }
    stamp(record)
    PATHWAYS[record["id"]] = record
    return ok(serialize.pathway(record), 201)


@bp.route("/corps/certification-pathways", methods=["GET"])
def list_pathways():
    require_auth(["PlatformAdmin", "CertificationOfficer"])
    region_id = request.args.get("region_id")
    rows = sorted_by_created(PATHWAYS.values())
    if region_id:
        rows = [r for r in rows if r["region_id"] == region_id]
    page, window = paginate(rows)
    return ok([serialize.pathway(r) for r in page], 200, page=window)


@bp.route("/corps/certification-pathways/<pathway_id>", methods=["GET"])
def get_pathway(pathway_id):
    require_auth(["PlatformAdmin", "CertificationOfficer"])
    pathway = PATHWAYS.get(pathway_id)
    if pathway is None:
        raise ApiError("ERR_PATHWAY_NOT_FOUND")
    return ok(serialize.pathway(pathway), 200)


@bp.route("/corps/certification-pathways/<pathway_id>/certification-milestones", methods=["GET"])
def list_pathway_milestones(pathway_id):
    require_auth(["PlatformAdmin", "CertificationOfficer"])
    pathway = PATHWAYS.get(pathway_id)
    if pathway is None:
        raise ApiError("ERR_PATHWAY_NOT_FOUND")
    rows = [m for m in sorted_by_created(MILESTONES.values()) if m["pathway_id"] == pathway_id]
    page, window = paginate(rows)
    return ok([serialize.milestone(m) for m in page], 200, page=window)


# --------------------------------------------------------------------------
# Certification milestones
# --------------------------------------------------------------------------
@bp.route("/corps/certification-milestones", methods=["POST"])
def create_milestone():
    require_auth(["CertificationOfficer"])
    body = read_json()
    validation.require(body, "corps_member_id", "pathway_id", "milestone_type", "required_hours")
    corps_member_id = validation.string(body, "corps_member_id")
    pathway_id = validation.string(body, "pathway_id")
    milestone_type = validation.enum(body, "milestone_type", validation.MILESTONE_TYPES)
    required_hours = validation.integer(body, "required_hours", minimum=0)
    due_date = validation.timestamp(body, "due_date", required=False)

    member = MEMBERS.get(corps_member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    pathway = PATHWAYS.get(pathway_id)
    if pathway is None:
        raise ApiError("ERR_PATHWAY_NOT_FOUND")

    application = APPLICATIONS.get(member.get("application_id"))
    member_region_id = application["preferred_region_id"] if application else None
    if member_region_id is not None and pathway["region_id"] != member_region_id:
        raise ApiError("ERR_PATHWAY_REGION_MISMATCH")

    if due_date is not None:
        due_iso = iso(due_date)
    else:
        region = REGIONS.get(pathway["region_id"])
        due_iso = iso(services.milestone_due_date(region, pathway))

    record = {
        "corps_member_id": corps_member_id,
        "pathway_id": pathway_id,
        "milestone_type": milestone_type,
        "required_hours": required_hours,
        "due_date": due_iso,
        "progress_status": "PENDING",
        "verification_status": "UNVERIFIED",
        "completed_at": None,
        "completed_by_user_id": None,
        "verified_by_user_id": None,
        "deadline_status": None,
        "days_remaining": 0,
        "synthesized": False,
    }
    stamp(record)
    MILESTONES[record["id"]] = record
    services.refresh_member(member)
    return ok(serialize.milestone(record), 201)


@bp.route("/corps/certification-milestones/<milestone_id>", methods=["GET"])
def get_milestone(milestone_id):
    require_auth(["PlacementCoordinator", "CertificationOfficer"])
    return ok(serialize.milestone(_load_milestone(milestone_id)), 200)


@bp.route("/corps/certification-milestones/<milestone_id>/start", methods=["POST"])
def start_milestone(milestone_id):
    require_auth(["CertificationOfficer"])
    read_json()
    milestone = _load_milestone(milestone_id)
    member = _owning_member(milestone)
    if milestone["progress_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING milestone can be started.")
    if milestone["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE", "The milestone's verification dimension is already closed.")
    if member["service_status"] not in ("ACTIVE", "ON_LEAVE"):
        raise ApiError("ERR_INVALID_STATE", "A member who has exited the corps cannot advance certification.")
    milestone["progress_status"] = "IN_PROGRESS"
    touch(milestone)
    return ok(serialize.milestone(milestone), 200)


@bp.route("/corps/certification-milestones/<milestone_id>/complete", methods=["POST"])
def complete_milestone(milestone_id):
    user_id, _role = require_auth(["CertificationOfficer"])
    read_json()
    milestone = _load_milestone(milestone_id)
    member = _owning_member(milestone)
    progress = milestone["progress_status"]
    if progress not in ("PENDING", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "The milestone is already complete.")
    if progress == "PENDING" and milestone["required_hours"] != 0:
        raise ApiError("ERR_INVALID_STATE", "Only a zero-hour milestone may complete straight from PENDING.")
    if member["institute_status"] not in ("IN_TRAINING", "COMPLETED"):
        raise ApiError("ERR_INVALID_STATE", "The pre-service institute has not started.")
    if dt_date(now()) > dt_date(milestone["due_date"]):
        raise ApiError("ERR_MILESTONE_PAST_DUE")
    milestone["progress_status"] = "COMPLETED"
    milestone["completed_at"] = iso(now())
    milestone["completed_by_user_id"] = user_id
    touch(milestone)
    services.refresh_member(member)
    return ok(serialize.milestone(milestone), 200)


@bp.route("/corps/certification-milestones/<milestone_id>/verify", methods=["POST"])
def verify_milestone(milestone_id):
    user_id, _role = require_auth(["CertificationOfficer"])
    body = read_json()
    outcome = validation.enum(body, "outcome", validation.VERIFY_OUTCOMES)
    milestone = _load_milestone(milestone_id)
    member = _owning_member(milestone)
    if milestone["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE", "The milestone's verification dimension is already closed.")
    if milestone["progress_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Only a completed milestone can be verified.")
    if user_id == milestone["completed_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", "The verifying officer must differ from the completing officer.")
    milestone["verification_status"] = "VERIFIED" if outcome == "VERIFY" else "REJECTED"
    milestone["verified_by_user_id"] = user_id
    touch(milestone)
    services.refresh_member(member)
    services.refresh_member_placements(member)
    return ok(serialize.milestone(milestone), 200)

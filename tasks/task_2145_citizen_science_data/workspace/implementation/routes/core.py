"""Protocols, volunteers, experts and certifications."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import response
import services
from errors import ApiError

bp = Blueprint("core", __name__)

LEVELS = ["BASIC", "ADVANCED", "EXPERT"]
EQUIPMENT_TYPES = ["NONE", "ACOUSTIC_RECORDER", "GPS_LOGGER", "SPOTTING_SCOPE"]


def _page(rows, filters):
    rows = guards.apply_filters(rows, filters)
    page, limit, offset, total = guards.paginate(rows)
    return response.list_response([db.serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Protocols
# --------------------------------------------------------------------------
@bp.post("/citizen-science/protocols")
def create_protocol():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "code", "type": "string", "required": True},
        {"name": "title", "type": "string", "required": True},
        {"name": "required_certification_level", "type": "enum", "required": True, "values": LEVELS},
        {"name": "min_photo_count", "type": "integer", "required": True, "min": 0},
        {"name": "max_submission_lag_hours", "type": "integer", "required": True, "gt": 0},
        {"name": "required_equipment_type", "type": "enum", "required": False,
         "values": EQUIPMENT_TYPES, "default": "NONE"},
        {"name": "certification_valid_days", "type": "integer", "required": False,
         "gt": 0, "default": 365},
        {"name": "supersedes_protocol_id", "type": "id", "required": False, "default": None},
    ])

    version_number = 1
    if body["supersedes_protocol_id"] is not None:
        parent = guards.get_protocol(body["supersedes_protocol_id"])
        version_number = parent["version_number"] + 1

    guards.require_unique(db.protocols, "code", body["code"])

    row = db.new_row({
        "code": body["code"],
        "title": body["title"],
        "version_number": version_number,
        "supersedes_protocol_id": body["supersedes_protocol_id"],
        "status": "DRAFT",
        "required_certification_level": body["required_certification_level"],
        "min_photo_count": body["min_photo_count"],
        "max_submission_lag_hours": body["max_submission_lag_hours"],
        "required_equipment_type": body["required_equipment_type"],
        "certification_valid_days": body["certification_valid_days"],
        "activated_at": None,
    })
    db.protocols[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/protocols")
def list_protocols():
    actor = guards.authenticate(["ProgramAdmin", "Volunteer", "Expert", "ResearchPartner"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.protocols), ["status", "code", "supersedes_protocol_id"])


@bp.get("/citizen-science/protocols/<pid>")
def read_protocol(pid):
    actor = guards.authenticate(["ProgramAdmin", "Volunteer", "Expert", "ResearchPartner"])
    row = guards.get_protocol(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/protocols/<pid>/activate")
def activate_protocol(pid):
    guards.authenticate(["ProgramAdmin"])
    protocol = guards.get_protocol(pid)
    if protocol["status"] != "DRAFT":
        raise ApiError("ERR_PROTOCOL_NOT_DRAFT")

    protocol["status"] = "ACTIVE"
    protocol["activated_at"] = clock.now()
    db.touch(protocol)

    prior_id = protocol["supersedes_protocol_id"]
    if prior_id:
        prior = db.protocols.get(prior_id)
        if prior is not None and prior["status"] == "ACTIVE":
            services.retire_protocol(prior)

    return response.object_response(db.serialize(protocol))


# --------------------------------------------------------------------------
# Volunteers
# --------------------------------------------------------------------------
@bp.post("/citizen-science/volunteers")
def create_volunteer():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "full_name", "type": "string", "required": True},
        {"name": "email", "type": "string", "required": True},
        {"name": "home_region_code", "type": "string", "required": True},
    ])
    guards.require_unique(db.volunteers, "email", body["email"])
    row = db.new_row({
        "full_name": body["full_name"],
        "email": body["email"],
        "home_region_code": body["home_region_code"],
        "status": "PENDING",
        "quality_score": Decimal("0.5"),
        "lifetime_quality_score": Decimal("0.5"),
        "recognition_tier": "BRONZE",
        "lifetime_points": 0,
        "accepted_observation_count": 0,
        "rejected_observation_count": 0,
        "consecutive_accepted": 0,
        "consecutive_rejections": 0,
    })
    db.volunteers[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/volunteers")
def list_volunteers():
    actor = guards.authenticate(["ProgramAdmin", "Expert"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.volunteers), ["status", "recognition_tier", "home_region_code"])


@bp.get("/citizen-science/volunteers/<pid>")
def read_volunteer(pid):
    actor = guards.authenticate(["ProgramAdmin", "Expert", "Volunteer"])
    row = guards.get_volunteer(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/volunteers/<pid>/reinstate")
def reinstate_volunteer(pid):
    guards.authenticate(["ProgramAdmin"])
    volunteer = guards.get_volunteer(pid)
    if volunteer["status"] not in ("PROBATION", "SUSPENDED"):
        raise ApiError("ERR_VOLUNTEER_NOT_IN_GOOD_STANDING")
    if calc.dec(volunteer["quality_score"]) < calc.PROBATION_FLOOR:
        raise ApiError("ERR_VOLUNTEER_NOT_IN_GOOD_STANDING")

    volunteer["status"] = "ACTIVE"
    volunteer["consecutive_rejections"] = 0
    db.touch(volunteer)
    for cert in services.volunteer_certifications(volunteer["id"]):
        if cert["status"] == "SUSPENDED" and cert["suspended_reason"] == "QUALITY_PROBATION":
            cert["status"] = "CERTIFIED"
            cert["suspended_reason"] = "NONE"
            db.touch(cert)
    return response.object_response(db.serialize(volunteer))


# --------------------------------------------------------------------------
# Experts
# --------------------------------------------------------------------------
@bp.post("/citizen-science/experts")
def create_expert():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "full_name", "type": "string", "required": True},
        {"name": "specialty_taxon", "type": "string", "required": True},
        {"name": "verification_weight", "type": "number", "required": True,
         "min": Decimal("0.50"), "max": Decimal("4.00")},
        {"name": "linked_volunteer_id", "type": "id", "required": False, "default": None},
    ])
    if body["linked_volunteer_id"] is not None:
        guards.get_volunteer(body["linked_volunteer_id"])
    row = db.new_row({
        "full_name": body["full_name"],
        "specialty_taxon": body["specialty_taxon"],
        "verification_weight": calc.rnd(body["verification_weight"], 2),
        "linked_volunteer_id": body["linked_volunteer_id"],
        "status": "ACTIVE",
        "vote_count": 0,
        "retracted_confirm_count": 0,
    })
    db.experts[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/experts")
def list_experts():
    actor = guards.authenticate(["ProgramAdmin", "Expert"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.experts), ["status", "specialty_taxon", "linked_volunteer_id"])


@bp.get("/citizen-science/experts/<pid>")
def read_expert(pid):
    actor = guards.authenticate(["ProgramAdmin", "Expert"])
    row = guards.get_expert(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.get("/citizen-science/experts/<pid>/votes")
def list_expert_votes(pid):
    actor = guards.authenticate(["ProgramAdmin", "Expert"])
    expert = guards.get_expert(pid)
    guards.resolve_actor(actor)
    rows = sorted([v for v in db.votes.values() if v["expert_id"] == expert["id"]],
                  key=db.order_key)
    return _page(rows, [])


# --------------------------------------------------------------------------
# Certifications
# --------------------------------------------------------------------------
@bp.post("/citizen-science/certifications")
def create_certification():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "volunteer_id", "type": "id", "required": True},
        {"name": "protocol_id", "type": "id", "required": True},
        {"name": "trainer_expert_id", "type": "id", "required": True},
        {"name": "level", "type": "enum", "required": True, "values": LEVELS},
    ])
    guards.get_protocol(body["protocol_id"])
    guards.get_volunteer(body["volunteer_id"])
    guards.get_expert(body["trainer_expert_id"])

    row = db.new_row({
        "volunteer_id": body["volunteer_id"],
        "protocol_id": body["protocol_id"],
        "trainer_expert_id": body["trainer_expert_id"],
        "level": body["level"],
        "status": "ENROLLED",
        "exam_score": None,
        "granted_at": None,
        "expires_at": None,
        "suspended_reason": "NONE",
    })
    db.certifications[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/certifications")
def list_certifications():
    actor = guards.authenticate(["ProgramAdmin", "Expert", "Volunteer"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.certifications),
                 ["volunteer_id", "protocol_id", "trainer_expert_id", "status"])


@bp.get("/citizen-science/certifications/<pid>")
def read_certification(pid):
    actor = guards.authenticate(["ProgramAdmin", "Expert", "Volunteer"])
    row = guards.get_certification(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/certifications/<pid>/complete-training")
def complete_training(pid):
    actor = guards.authenticate(["Expert"])
    cert = guards.get_certification(pid)
    guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "exam_score", "type": "integer", "required": True, "min": 0, "max": 100},
    ])
    if cert["trainer_expert_id"] != actor["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if cert["status"] != "ENROLLED":
        raise ApiError("ERR_CERTIFICATION_STATE_INVALID")
    if body["exam_score"] < calc.PASSING_EXAM_SCORE:
        raise ApiError("ERR_EXAM_SCORE_TOO_LOW")

    cert["status"] = "TRAINED"
    cert["exam_score"] = body["exam_score"]
    db.touch(cert)
    return response.object_response(db.serialize(cert))


@bp.post("/citizen-science/certifications/<pid>/grant")
def grant_certification(pid):
    guards.authenticate(["ProgramAdmin"])
    cert = guards.get_certification(pid)
    if cert["status"] != "TRAINED":
        raise ApiError("ERR_CERTIFICATION_STATE_INVALID")
    protocol = db.protocols.get(cert["protocol_id"])
    if protocol is None or protocol["status"] != "ACTIVE":
        raise ApiError("ERR_PROTOCOL_NOT_ACTIVE")

    granted_at = clock.now()
    cert["status"] = "CERTIFIED"
    cert["granted_at"] = granted_at
    cert["expires_at"] = clock.plus_days(granted_at, protocol["certification_valid_days"])
    db.touch(cert)

    volunteer = db.volunteers.get(cert["volunteer_id"])
    if volunteer is not None and volunteer["status"] == "PENDING":
        volunteer["status"] = "ACTIVE"
        db.touch(volunteer)

    return response.object_response(db.serialize(cert))

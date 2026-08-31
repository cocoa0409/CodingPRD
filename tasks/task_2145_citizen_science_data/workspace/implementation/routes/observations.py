"""Observations, photo evidence and verification votes."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import response
import services
from errors import ApiError

bp = Blueprint("observations", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Expert", "ResearchPartner"]
DECISIONS = ["CONFIRM", "REJECT", "REQUEST_REVISION"]


def _page(rows, filters):
    rows = guards.apply_filters(rows, filters)
    page, limit, offset, total = guards.paginate(rows)
    return response.list_response([db.serialize(r) for r in page], limit, offset, total)


def _valid_certifications(volunteer_id, protocol_id):
    now = clock.now()
    out = []
    for cert in services.volunteer_certifications(volunteer_id):
        if cert["protocol_id"] != protocol_id:
            continue
        if cert["status"] != "CERTIFIED":
            continue
        if cert["expires_at"] is None or not cert["expires_at"] > now:
            continue
        out.append(cert)
    return out


# --------------------------------------------------------------------------
# submit
# --------------------------------------------------------------------------
@bp.post("/citizen-science/observations")
def create_observation():
    actor = guards.authenticate(["Volunteer"])
    guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "campaign_id", "type": "id", "required": True},
        {"name": "site_id", "type": "id", "required": True},
        {"name": "volunteer_id", "type": "id", "required": True},
        {"name": "observed_at", "type": "datetime", "required": True},
        {"name": "latitude", "type": "number", "required": True},
        {"name": "longitude", "type": "number", "required": True},
        {"name": "species_code", "type": "string", "required": True},
        {"name": "count_value", "type": "integer", "required": True, "min": 0},
        {"name": "equipment_loan_id", "type": "id", "required": False, "default": None},
    ])

    # priority 7 — body foreign keys
    volunteer = guards.get_volunteer(body["volunteer_id"])
    campaign = guards.get_campaign(body["campaign_id"])
    site = guards.get_site(body["site_id"])
    loan = None
    if body["equipment_loan_id"] is not None:
        loan = guards.get_loan(body["equipment_loan_id"])

    # priority 8 — ownership
    if volunteer["id"] != actor["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # priority 22 — campaign state
    if campaign["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")

    protocol = db.protocols.get(campaign["protocol_id"])

    # priority 30 — volunteer standing
    if volunteer["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_VOLUNTEER_NOT_IN_GOOD_STANDING")

    # priority 31 — valid certification
    certs = _valid_certifications(volunteer["id"], campaign["protocol_id"])
    if not certs:
        raise ApiError("ERR_CERTIFICATION_NOT_VALID")

    # priority 32 — certification level
    best = max(calc.LEVEL_RANK[c["level"]] for c in certs)
    if best < calc.LEVEL_RANK[protocol["required_certification_level"]]:
        raise ApiError("ERR_CERTIFICATION_LEVEL_INSUFFICIENT")

    # priority 33 — equipment requirement
    required_type = protocol["required_equipment_type"]
    if required_type != "NONE":
        if loan is None or loan["status"] != "ISSUED" or loan["volunteer_id"] != volunteer["id"]:
            raise ApiError("ERR_EQUIPMENT_REQUIREMENT_UNMET")
        unit = db.equipment.get(loan["equipment_id"])
        if unit is None or unit["equipment_type"] != required_type:
            raise ApiError("ERR_EQUIPMENT_REQUIREMENT_UNMET")

    # priority 36 — site belongs to campaign
    if site["campaign_id"] != campaign["id"]:
        raise ApiError("ERR_SITE_CAMPAIGN_MISMATCH")

    # priority 40 — observation inside season
    observed_date = body["observed_at"].date()
    if observed_date < campaign["_season_start"] or observed_date > campaign["_season_end"]:
        raise ApiError("ERR_OBSERVED_OUTSIDE_SEASON")

    # priority 41 — submission lag
    now = clock.now()
    lag = calc.hours_between(body["observed_at"], now)
    if lag > Decimal(protocol["max_submission_lag_hours"]):
        raise ApiError("ERR_SUBMISSION_LAG_EXCEEDED")

    # priority 53 — site saturation
    if site["accepted_observation_count"] >= calc.SATURATION_MULTIPLIER * campaign["target_observations_per_site"]:
        raise ApiError("ERR_SITE_SATURATED")

    row = db.new_row({
        "campaign_id": campaign["id"],
        "site_id": site["id"],
        "volunteer_id": volunteer["id"],
        "equipment_loan_id": body["equipment_loan_id"],
        "publication_id": None,
        "observed_at": body["observed_at"],
        "submitted_at": now,
        "latitude": body["latitude"],
        "longitude": body["longitude"],
        "species_code": body["species_code"],
        "count_value": body["count_value"],
        "photo_count": 0,
        "review_status": "SUBMITTED",
        "publication_status": "UNPUBLISHED",
        "revision_round": 0,
        "provisional_quality_points": calc.rnd(Decimal("0.0"), 2),
        "final_quality_points": calc.rnd(Decimal("0.0"), 2),
        "consensus_confidence": calc.rnd(Decimal("0.0"), 4),
        "confirm_weight": calc.rnd(Decimal("0.0"), 4),
        "reject_weight": calc.rnd(Decimal("0.0"), 4),
        "revision_weight": calc.rnd(Decimal("0.0"), 4),
    })
    row["provisional_quality_points"] = calc.provisional_points(row, protocol, site)
    db.observations[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/observations")
def list_observations():
    actor = guards.authenticate(ALL_ROLES)
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.observations),
                 ["campaign_id", "site_id", "volunteer_id", "equipment_loan_id",
                  "publication_id", "review_status", "publication_status"])


@bp.get("/citizen-science/observations/<pid>")
def read_observation(pid):
    actor = guards.authenticate(ALL_ROLES)
    row = guards.get_observation(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


# --------------------------------------------------------------------------
# photo evidence
# --------------------------------------------------------------------------
@bp.post("/citizen-science/observations/<pid>/photos")
def create_photo(pid):
    actor = guards.authenticate(["Volunteer"])
    observation = guards.get_observation(pid)
    guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "file_hash", "type": "string", "required": True},
        {"name": "captured_at", "type": "datetime", "required": True},
        {"name": "exif_latitude", "type": "number", "required": True},
        {"name": "exif_longitude", "type": "number", "required": True},
    ])
    if observation["volunteer_id"] != actor["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    guards.require_unique(db.photos, "file_hash", body["file_hash"],
                          "observation_id", observation["id"])

    delta = calc.geo_delta(body["exif_latitude"], body["exif_longitude"],
                           observation["latitude"], observation["longitude"])
    status = calc.screen_photo(body["captured_at"], observation["observed_at"], delta)

    row = db.new_row({
        "observation_id": observation["id"],
        "file_hash": body["file_hash"],
        "captured_at": body["captured_at"],
        "exif_latitude": body["exif_latitude"],
        "exif_longitude": body["exif_longitude"],
        "geo_delta_meters": delta,
        "status": status,
    })
    db.photos[row["id"]] = row

    observation["photo_count"] = sum(
        1 for p in db.photos.values()
        if p["observation_id"] == observation["id"] and p["status"] == "ACCEPTED")
    campaign = db.campaigns[observation["campaign_id"]]
    protocol = db.protocols[campaign["protocol_id"]]
    site = db.sites[observation["site_id"]]
    observation["provisional_quality_points"] = calc.provisional_points(observation, protocol, site)
    db.touch(observation)

    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/observations/<pid>/photos")
def list_photos(pid):
    actor = guards.authenticate(["ProgramAdmin", "Volunteer", "Expert"])
    observation = guards.get_observation(pid)
    guards.resolve_actor(actor)
    return _page(services.observation_photos(observation["id"]), ["status"])


# --------------------------------------------------------------------------
# review
# --------------------------------------------------------------------------
@bp.post("/citizen-science/observations/<pid>/start-review")
def start_review(pid):
    actor = guards.authenticate(["Expert"])
    observation = guards.get_observation(pid)
    expert = guards.resolve_actor(actor)

    # priority 9 — self-verification bar
    if expert["linked_volunteer_id"] is not None and \
            expert["linked_volunteer_id"] == observation["volunteer_id"]:
        raise ApiError("ERR_SELF_VERIFICATION")

    # priority 23 — review state
    if observation["review_status"] != "SUBMITTED":
        raise ApiError("ERR_OBSERVATION_STATE_INVALID")

    # priority 34 — expert standing
    if expert["status"] != "ACTIVE":
        raise ApiError("ERR_EXPERT_SUSPENDED")

    campaign = db.campaigns[observation["campaign_id"]]
    protocol = db.protocols[campaign["protocol_id"]]

    # priority 50 — photo evidence sufficiency
    if observation["photo_count"] < protocol["min_photo_count"]:
        raise ApiError("ERR_PHOTO_EVIDENCE_INSUFFICIENT")

    # review may only start while the campaign is OPEN or CLOSED
    if campaign["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")

    observation["review_status"] = "UNDER_REVIEW"
    db.touch(observation)
    return response.object_response(db.serialize(observation))


@bp.post("/citizen-science/observations/<pid>/votes")
def cast_vote(pid):
    actor = guards.authenticate(["Expert"])
    observation = guards.get_observation(pid)
    expert = guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "decision", "type": "enum", "required": True, "values": DECISIONS},
        {"name": "confidence", "type": "integer", "required": True, "min": 1, "max": 5},
        {"name": "expected_observation_version", "type": "integer", "required": True},
        {"name": "comment", "type": "string", "required": False, "allow_empty": True,
         "default": None},
    ])

    # priority 9 — self-verification bar
    if expert["linked_volunteer_id"] is not None and \
            expert["linked_volunteer_id"] == observation["volunteer_id"]:
        raise ApiError("ERR_SELF_VERIFICATION")

    # priority 10 — trainer-conflict bar
    if observation["revision_round"] == 0:
        campaign_row = db.campaigns[observation["campaign_id"]]
        for cert in services.volunteer_certifications(observation["volunteer_id"]):
            if cert["protocol_id"] == campaign_row["protocol_id"] and \
                    cert["trainer_expert_id"] == expert["id"]:
                raise ApiError("ERR_TRAINER_VERIFICATION_CONFLICT")

    # priority 11 — duplicate vote
    for vote in db.votes.values():
        if (vote["observation_id"] == observation["id"]
                and vote["expert_id"] == expert["id"]
                and vote["round_number"] == observation["revision_round"]):
            raise ApiError("ERR_DUPLICATE_VOTE")

    # priority 12 — optimistic concurrency
    if body["expected_observation_version"] != observation["version"]:
        raise ApiError("ERR_STALE_OBSERVATION_VERSION")

    # priority 23 — review state
    if observation["review_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_OBSERVATION_STATE_INVALID")

    # priority 34 — expert standing
    if expert["status"] != "ACTIVE":
        raise ApiError("ERR_EXPERT_SUSPENDED")

    row = db.new_row({
        "observation_id": observation["id"],
        "expert_id": expert["id"],
        "round_number": observation["revision_round"],
        "decision": body["decision"],
        "confidence": body["confidence"],
        "weight_applied": calc.vote_weight(expert, body["confidence"]),
        "comment": body["comment"],
    }, common=False)
    db.votes[row["id"]] = row

    expert["vote_count"] += 1
    db.touch(expert)

    outcome = calc.consensus(observation)
    db.touch(observation)

    if outcome == "ACCEPT":
        services.apply_acceptance(observation)
    elif outcome == "REJECT":
        services.apply_rejection(observation)
    elif outcome == "REVISE":
        observation["review_status"] = "NEEDS_REVISION"
        db.touch(observation)

    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/observations/<pid>/votes")
def list_votes(pid):
    actor = guards.authenticate(["ProgramAdmin", "Volunteer", "Expert"])
    observation = guards.get_observation(pid)
    guards.resolve_actor(actor)
    return _page(services.observation_votes(observation["id"]), ["round_number"])


@bp.post("/citizen-science/observations/<pid>/resubmit")
def resubmit_observation(pid):
    actor = guards.authenticate(["Volunteer"])
    observation = guards.get_observation(pid)
    guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "latitude", "type": "number", "required": False},
        {"name": "longitude", "type": "number", "required": False},
        {"name": "species_code", "type": "string", "required": False},
        {"name": "count_value", "type": "integer", "required": False, "min": 0},
    ])

    # priority 8 — ownership
    if observation["volunteer_id"] != actor["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    campaign = db.campaigns[observation["campaign_id"]]
    protocol = db.protocols[campaign["protocol_id"]]

    # priority 22 — campaign state
    if campaign["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")

    # priority 23 — review state
    if observation["review_status"] != "NEEDS_REVISION":
        raise ApiError("ERR_OBSERVATION_STATE_INVALID")

    volunteer = db.volunteers[observation["volunteer_id"]]

    # priority 30 — volunteer standing
    if volunteer["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_VOLUNTEER_NOT_IN_GOOD_STANDING")

    # priority 31 — valid certification
    if not _valid_certifications(volunteer["id"], campaign["protocol_id"]):
        raise ApiError("ERR_CERTIFICATION_NOT_VALID")

    # priority 49 — revision budget
    if observation["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    for field in ("latitude", "longitude", "species_code", "count_value"):
        if field in body:
            observation[field] = body[field]

    observation["review_status"] = "SUBMITTED"
    observation["revision_round"] += 1
    observation["submitted_at"] = clock.now()
    site = db.sites[observation["site_id"]]
    observation["provisional_quality_points"] = calc.provisional_points(observation, protocol, site)
    db.touch(observation)
    return response.object_response(db.serialize(observation))


@bp.post("/citizen-science/observations/<pid>/retract")
def retract_observation(pid):
    guards.authenticate(["ProgramAdmin"])
    observation = guards.get_observation(pid)
    guards.validate_body([
        {"name": "reason", "type": "string", "required": True},
    ])
    if observation["review_status"] != "ACCEPTED":
        raise ApiError("ERR_OBSERVATION_STATE_INVALID")

    services.apply_retraction(observation)
    return response.object_response(db.serialize(observation))

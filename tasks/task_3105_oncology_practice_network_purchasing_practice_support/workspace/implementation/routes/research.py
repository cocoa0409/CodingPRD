"""Research participations: the community-site clinical trial lifecycle."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services.helpers import as_enum, as_int, as_str

READ_ROLES = ["NetworkAdmin", "PracticeAdmin", "NetworkAnalyst", "PlatformAdmin"]

LIVE_SITE_STATUSES = ("APPLIED", "FEASIBILITY_REVIEW", "ACTIVATED", "SUSPENDED")


@route(
    "POST",
    "/networks/practices/{practiceId}/research-participations",
    roles=["NetworkAdmin"],
    status=201,
    write=True,
)
def create_participation(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    data = ctx.body
    participation = db.create(
        "research_participations",
        {
            "practice_id": practice["id"],
            "network_id": practice["network_id"],
            "study_protocol_number": as_str(data, "study_protocol_number"),
            "study_phase": as_enum(
                data, "study_phase", ("PHASE_I", "PHASE_II", "PHASE_III"), required_=True
            ),
            "sponsor_name": as_str(data, "sponsor_name"),
            "target_enrollment": as_int(data, "target_enrollment", required_=True),
            "enrolled_participant_count": 0,
            "site_status": "APPLIED",
        },
    )
    return serial(participation), 201


@route("GET", "/networks/research-participations", roles=READ_ROLES)
def list_participations(ctx):
    rows = filtered(
        db.all_records("research_participations"),
        ctx,
        {
            "practice_id": "practice_id",
            "network_id": "network_id",
            "site_status": "site_status",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/research-participations/{participationId}", roles=READ_ROLES)
def get_participation(ctx):
    return serial(helpers.participation_or_404(ctx.path_id("participationId")))


@route(
    "POST",
    "/networks/research-participations/{participationId}/begin-feasibility",
    roles=["NetworkAdmin"],
    write=True,
)
def begin_feasibility(ctx):
    participation = helpers.participation_or_404(ctx.path_id("participationId"))
    practice = helpers.practice_or_404(participation["practice_id"])
    if participation["site_status"] != "APPLIED":
        raise ApiError("ERR_SITE_NOT_APPLIED")
    if (
        practice["affiliation_status"] != "AFFILIATED"
        or practice["pathway_steering_status"] != "ACTIVE"
    ):
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")
    participation["site_status"] = "FEASIBILITY_REVIEW"
    db.touch(participation)
    return serial(participation)


@route(
    "POST",
    "/networks/research-participations/{participationId}/activate",
    roles=["NetworkAdmin"],
    write=True,
)
def activate_participation(ctx):
    participation = helpers.participation_or_404(ctx.path_id("participationId"))
    practice = helpers.practice_or_404(participation["practice_id"])
    if participation["site_status"] not in ("FEASIBILITY_REVIEW", "SUSPENDED"):
        raise ApiError("ERR_SITE_NOT_IN_FEASIBILITY")
    if participation["site_status"] == "FEASIBILITY_REVIEW":
        already = [
            p
            for p in db.where("research_participations", practice_id=practice["id"])
            if p["site_status"] == "ACTIVATED" and p["id"] != participation["id"]
        ]
        if already:
            raise ApiError("ERR_SITE_ALREADY_ACTIVE_TRIAL")
        participation["enrolled_participant_count"] = 0
    participation["site_status"] = "ACTIVATED"
    db.touch(participation)
    return serial(participation)


@route(
    "POST",
    "/networks/research-participations/{participationId}/suspend",
    roles=["NetworkAdmin"],
    write=True,
)
def suspend_participation(ctx):
    participation = helpers.participation_or_404(ctx.path_id("participationId"))
    practice = helpers.practice_or_404(participation["practice_id"])
    if participation["site_status"] != "ACTIVATED":
        raise ApiError("ERR_SITE_NOT_ACTIVATED")
    participation["site_status"] = "SUSPENDED"
    # A research hold freezes the practice's rebate compliance contribution at
    # the value it held on the day of suspension.
    for contract in db.where("affiliation_contracts", practice_id=practice["id"]):
        contract["research_hold"] = True
        contract["research_hold_adherence_pct"] = practice.get("pathway_adherence_pct")
        db.touch(contract)
    db.touch(participation)
    return serial(participation)


@route(
    "POST",
    "/networks/research-participations/{participationId}/deactivate",
    roles=["NetworkAdmin"],
    write=True,
)
def deactivate_participation(ctx):
    participation = helpers.participation_or_404(ctx.path_id("participationId"))
    if participation["site_status"] not in ("ACTIVATED", "SUSPENDED"):
        raise ApiError("ERR_SITE_NOT_ACTIVATED")
    participation["site_status"] = "DEACTIVATED"
    db.touch(participation)
    return serial(participation)


@route(
    "POST",
    "/networks/research-participations/{participationId}/enroll-participant",
    roles=["NetworkAdmin"],
    status=201,
    write=True,
)
def enroll_participant(ctx):
    participation = helpers.participation_or_404(ctx.path_id("participationId"))
    as_str(ctx.body, "participant_reference")
    participation["enrolled_participant_count"] = int(
        participation.get("enrolled_participant_count") or 0
    ) + 1
    db.touch(participation)
    return serial(participation), 201
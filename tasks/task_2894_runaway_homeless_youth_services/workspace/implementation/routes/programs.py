"""Shelter programs, the federal compliance report and program-scoped proposals."""

from flask import Blueprint

import authz
import calc
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("programs", __name__)

PROGRAM_TYPES = ("EMERGENCY_SHELTER", "TRANSITIONAL_LIVING")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
PROPOSAL_CATEGORIES = ("HOUSE_RULES", "PROGRAMMING", "GRIEVANCE_PROCESS", "FOOD_SERVICE")
PROPOSAL_STATUSES = ("OPEN_FOR_VOTE", "ADOPTED", "REJECTED")


@bp.post("/ryhs/shelter-programs")
def create_program():
    authz.require(authz.PROGRAM_ADMIN)
    body = shape.body()
    name = shape.need_str(body, "name", 1, 120)
    program_type = shape.need_enum(body, "program_type", PROGRAM_TYPES)
    capacity = shape.need_int(body, "licensed_bed_capacity", 1, None)
    min_age = shape.need_int(body, "min_age_years", 0, 24)
    max_age = shape.need_int(body, "max_age_years", min_age, 24)
    max_stay_nights = shape.need_int(body, "max_stay_nights", 1, None)
    max_placement_days = shape.need_int(body, "max_placement_days", 1, None)
    match_rate = shape.need_int(body, "savings_match_rate_bp", 0, 10000)
    required_rate = shape.need_int(body, "required_savings_rate_bp", 0, 10000)

    record = {
        "name": name,
        "program_type": program_type,
        "licensed_bed_capacity": capacity,
        "min_age_years": min_age,
        "max_age_years": max_age,
        "max_stay_nights": max_stay_nights,
        "max_placement_days": max_placement_days,
        "savings_match_rate_bp": match_rate,
        "required_savings_rate_bp": required_rate,
        "occupied_beds": 0,
        "waitlisted_count": 0,
        "overdue_notification_count": 0,
        "utilization_bp": 0,
        # PRD 3.3: a newly licensed program starts with posture computed as OPEN.
        "posture": calc.posture_for(0, 0, 0, capacity),
    }
    store.stamp_new(record)
    store.programs[record["id"]] = record
    return envelope.created(serial.program(record))


@bp.get("/ryhs/shelter-programs")
def list_programs():
    authz.require(*authz.STAFF_READ_ALL)
    program_type = envelope.enum_filter("program_type", PROGRAM_TYPES)
    posture = envelope.enum_filter("posture", POSTURES)
    rows = list(store.programs.values())
    if program_type is not None:
        rows = [r for r in rows if r["program_type"] == program_type]
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    return envelope.listing(store.ordered(rows), serial.program)


@bp.get("/ryhs/shelter-programs/<program_id>")
def read_program(program_id):
    authz.require(*authz.STAFF_READ_ALL)
    return envelope.ok(serial.program(find.program(program_id)))


@bp.get("/ryhs/shelter-programs/<program_id>/compliance-report")
def compliance_report(program_id):
    authz.require(authz.PROGRAM_ADMIN)
    program = find.program(program_id)
    return envelope.ok(calc.compliance_report(program))


@bp.post("/ryhs/shelter-programs/<program_id>/governance-proposals")
def open_proposal(program_id):
    user_id, role = authz.require(authz.PROGRAM_ADMIN, authz.YOUTH_MEMBER)
    program = find.program(program_id)
    body = shape.body()
    title = shape.need_str(body, "title", 1, 160)
    category = shape.need_enum(body, "category", PROPOSAL_CATEGORIES)
    closes_at = shape.need_instant(body, "voting_closes_at")
    # Ladder 32: caller-supplied instants lie in the future.
    if not closes_at > store.now():
        fail("ERR_INVALID_INTERVAL", "voting_closes_at must be later than the current clock")
    # Ladder 39: a YouthMember opener must itself be a vote-eligible resident.
    if role == authz.YOUTH_MEMBER:
        youth = store.youths.get(user_id)
        if (
            youth is None
            or not youth["governance_vote_eligible"]
            or not calc.is_resident(youth["id"], program["id"])
        ):
            fail("ERR_YOUTH_NOT_VOTE_ELIGIBLE")

    record = {
        "program_id": program["id"],
        "title": title,
        "category": category,
        "status": "OPEN_FOR_VOTE",
        "voting_closes_at": closes_at,
        "support_vote_count": 0,
        "oppose_vote_count": 0,
        # PRD 3.9: stays 0 until the vote is closed and the electorate is frozen.
        "eligible_electorate_size": 0,
        "support_ratio_bp": 0,
        "adopted_at": None,
        "decided_by_user_id": None,
    }
    store.stamp_new(record)
    store.governance_proposals[record["id"]] = record
    return envelope.created(serial.proposal(record))


@bp.get("/ryhs/shelter-programs/<program_id>/governance-proposals")
def list_program_proposals(program_id):
    authz.require(*(authz.STAFF_READ_ALL + (authz.YOUTH_MEMBER,)))
    program = find.program(program_id)
    status = envelope.enum_filter("status", PROPOSAL_STATUSES)
    rows = [
        p for p in store.governance_proposals.values() if p["program_id"] == program["id"]
    ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(store.ordered(rows), serial.proposal)

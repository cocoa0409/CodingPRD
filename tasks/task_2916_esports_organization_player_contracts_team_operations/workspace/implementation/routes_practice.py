"""Team houses, practice scheduling and the weekly workload gates (PRD section 3.5)."""

from flask import Blueprint

import calc
import cascade
import db
import response
import serializers as ser
import validation as v
from auth import endpoint, caller, require_org_owner
from db import store
from errors import fail

bp = Blueprint("practice", __name__)

BLOCK_TYPES = ("SCRIM", "REVIEW", "INDIVIDUAL", "TRYOUT")
BLOCK_STATES = ("SCHEDULED", "HELD", "CANCELLED")
CANCEL_REASONS = ("COACH_CANCELLED", "WELLNESS_HOLD", "CONTRACT_SUSPENDED")


# ======================================================================================
# team houses
# ======================================================================================

@bp.post("/organizations/<organization_id>/team-houses")
@endpoint(["OpsManager"])
def create_team_house(organization_id):
    organization = v.find_organization(organization_id)
    require_org_owner(organization["id"])
    payload = v.body()
    record = {
        # PRD section 2.10 -- nested creation takes the parent key from the PATH.
        "organization_id": organization["id"],
        "name": v.req_str(payload, "name", 1, 120),
        "timezone": v.req_str(payload, "timezone", 1, 64),
        "turnaround_buffer_minutes":
            v.opt_int(payload, "turnaround_buffer_minutes", 60, 0, 720),
        "concurrent_seat_capacity": v.opt_int(payload, "concurrent_seat_capacity", 10, 1),
    }
    db.insert(store.team_houses, record)
    return response.object_response(ser.team_house(record), 201)


@bp.get("/organizations/<organization_id>/team-houses")
@endpoint(["LeagueAdmin", "GeneralManager", "OpsManager", "CoachingStaff"])
def list_organization_team_houses(organization_id):
    organization = v.find_organization(organization_id)
    require_org_owner(organization["id"])
    limit, offset = response.pagination()
    records = [h for h in store.team_houses.values()
               if h["organization_id"] == organization["id"]]
    return response.paginated(db.in_creation_order(records), ser.team_house, limit, offset)


@bp.get("/team-houses/<team_house_id>")
@endpoint(["GeneralManager", "OpsManager", "CoachingStaff"])
def read_team_house(team_house_id):
    record = v.find_team_house(team_house_id)
    require_org_owner(record["organization_id"])
    return response.object_response(ser.team_house(record))


@bp.patch("/team-houses/<team_house_id>")
@endpoint(["OpsManager"])
def update_team_house(team_house_id):
    record = v.find_team_house(team_house_id)
    require_org_owner(record["organization_id"])
    payload = v.body()
    if v.present(payload, "name"):
        record["name"] = v.req_str(payload, "name", 1, 120)
    if v.present(payload, "turnaround_buffer_minutes"):
        record["turnaround_buffer_minutes"] = v.req_int(
            payload, "turnaround_buffer_minutes", 0, 720)
    if v.present(payload, "concurrent_seat_capacity"):
        record["concurrent_seat_capacity"] = v.req_int(payload, "concurrent_seat_capacity", 1)
    db.touch(record)
    return response.object_response(ser.team_house(record))


# ======================================================================================
# practice blocks
# ======================================================================================

def _contract_gate(player):
    """Band 8.  A participant with no contract at all is admitted; one who owns any
    contract in ACTIVE, SUSPENDED or TERMINATED must own an ACTIVE one."""
    contracts = calc.contracts_of_player(player["id"])
    if not contracts:
        return None
    active = [c for c in contracts if c["contract_status"] == "ACTIVE"]
    if not active:
        fail("ERR_CONTRACT_NOT_ACTIVE")
    return db.in_creation_order(active)[-1]


def _weekly_cap_gate(player, organization, candidate):
    """Band 9: the education reservation gets the narrower error only when it was decisive."""
    league = calc.governing_league_for_player(player, organization)
    if league is None:
        return
    minor = calc.is_minor(player, league=league)
    _scheduled, _streaming, committed = calc.weekly_committed_minutes(
        player, candidate["starts_at"], league, minor_flag=minor, extra_blocks=(candidate,))
    cap = calc.cap_minutes(player, league, minor_flag=minor)
    if committed <= cap:
        return
    cap_without_reserve = calc.cap_minutes(
        player, league, minor_flag=minor, education_reserved_override=0)
    if committed <= cap_without_reserve:
        fail("ERR_EDUCATION_HOURS_RESERVED")
    fail("ERR_WEEKLY_HOUR_CAP_EXCEEDED")


@bp.post("/practice-blocks")
@endpoint(["CoachingStaff"])
def create_practice_block():
    payload = v.body()
    organization_id = v.req_str(payload, "organization_id")
    team_house_id = v.req_str(payload, "team_house_id")
    block_type = v.req_enum(payload, "block_type", BLOCK_TYPES)
    starts_at = v.req_instant(payload, "starts_at")
    ends_at = v.req_instant(payload, "ends_at")
    participant_ids = v.req_id_list(payload, "participant_player_ids")
    coach_note = v.free_text(payload, "coach_note")
    if not ends_at > starts_at:
        fail("ERR_INVALID_REQUEST", "Field 'ends_at' must be after 'starts_at'.")

    # ---- band 6, left-to-right in the §2.6 order --------------------------------
    organization = v.find_organization(organization_id)
    participants = [v.find_player(pid) for pid in participant_ids]
    team_house = v.find_team_house(team_house_id)

    candidate = {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "duration_minutes": db.whole_minutes_between(starts_at, ends_at),
        "participant_player_ids": list(participant_ids),
    }

    # ---- band 8: every contract gate before any band-9 gate --------------------
    contracts = [_contract_gate(player) for player in participants]

    # ---- band 9, in the §2.6 internal order ------------------------------------
    for player in participants:
        if calc.guardian_consent_status(player, organization) == "REQUIRED":
            fail("ERR_GUARDIAN_CONSENT_REQUIRED")
    for player in participants:
        _weekly_cap_gate(player, organization, candidate)
    instant = db.now()
    for contract in contracts:
        if contract is None or contract["contract_status"] != "ACTIVE":
            continue
        hold_until = contract["wellness_hold_until"]
        if hold_until is not None and instant < hold_until:
            fail("ERR_WELLNESS_HOLD_ACTIVE")

    # ---- band 11 ---------------------------------------------------------------
    if calc.facility_slot_conflict(team_house, starts_at, ends_at):
        fail("ERR_FACILITY_SLOT_CONFLICT")
    for player in participants:
        if calc.participant_double_booked(player["id"], starts_at, ends_at):
            fail("ERR_PLAYER_DOUBLE_BOOKED")
    if calc.facility_capacity_exceeded(team_house, len(participant_ids)):
        fail("ERR_FACILITY_CAPACITY_EXCEEDED")

    user_id, _role = caller()
    record = {
        "organization_id": organization["id"],
        "team_house_id": team_house["id"],
        "block_type": block_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "duration_minutes": candidate["duration_minutes"],
        "participant_player_ids": list(participant_ids),
        "coach_user_id": user_id,
        "block_status": "SCHEDULED",
        "cancel_reason": None,
        "coach_note": coach_note,
    }
    db.insert(store.practice_blocks, record)

    # Booking a TRYOUT doubles as a scouting action.
    if block_type == "TRYOUT":
        for player in participants:
            if player["player_status"] in ("PROSPECT", "FREE_AGENT"):
                player["player_status"] = "TRYOUT_INVITED"
                db.touch(player)

    return response.object_response(ser.practice_block(record), 201)


@bp.get("/practice-blocks/<block_id>")
@endpoint(["GeneralManager", "OpsManager", "CoachingStaff", "PerformanceSupport"])
def read_practice_block(block_id):
    record = v.find_block(block_id)
    require_org_owner(record["organization_id"])
    return response.object_response(ser.practice_block(record))


@bp.get("/practice-blocks")
@endpoint(["GeneralManager", "OpsManager", "CoachingStaff", "PerformanceSupport"])
def list_practice_blocks():
    limit, offset = response.pagination()
    organization_id = v.str_filter("organization_id")
    team_house_id = v.str_filter("team_house_id")
    block_type = v.enum_filter("block_type", BLOCK_TYPES)
    block_status = v.enum_filter("block_status", BLOCK_STATES)
    starts_from = v.instant_filter("starts_from")
    starts_to = v.instant_filter("starts_to")
    records = list(store.practice_blocks.values())
    if organization_id is not None:
        records = [b for b in records if b["organization_id"] == organization_id]
    if team_house_id is not None:
        records = [b for b in records if b["team_house_id"] == team_house_id]
    if block_type is not None:
        records = [b for b in records if b["block_type"] == block_type]
    if block_status is not None:
        records = [b for b in records if b["block_status"] == block_status]
    if starts_from is not None:
        records = [b for b in records if b["starts_at"] >= starts_from]
    if starts_to is not None:
        records = [b for b in records if b["starts_at"] <= starts_to]
    return response.paginated(db.in_creation_order(records), ser.practice_block, limit, offset)


@bp.post("/practice-blocks/<block_id>/complete")
@endpoint(["CoachingStaff"])
def complete_practice_block(block_id):
    record = v.find_block(block_id)
    payload = v.body()
    coach_note = v.free_text(payload, "coach_note")
    if record["block_status"] != "SCHEDULED":
        fail("ERR_BLOCK_NOT_SCHEDULED")
    if db.now() < record["ends_at"]:
        fail("ERR_BLOCK_NOT_FINISHED")

    record["block_status"] = "HELD"
    if coach_note is not None:
        record["coach_note"] = coach_note
    db.touch(record)

    # The four-link cascade of §3.5.  The block is already HELD so the rolling window
    # picks its minutes up.
    for player_id in record["participant_player_ids"]:
        contract = calc.contract_of_player(player_id, statuses=("ACTIVE",))
        if contract is None:
            continue
        contract["season_practice_minutes"] += record["duration_minutes"]
        cascade.refresh_burnout_and_escalate(contract)
        db.touch(contract)

    if record["block_type"] == "TRYOUT":
        for player_id in record["participant_player_ids"]:
            player = store.players.get(player_id)
            if player is not None and player["player_status"] == "TRYOUT_INVITED":
                player["player_status"] = "TRYOUT_COMPLETED"
                db.touch(player)

    return response.object_response(ser.practice_block(record))


@bp.post("/practice-blocks/<block_id>/cancel")
@endpoint(["CoachingStaff"])
def cancel_practice_block(block_id):
    record = v.find_block(block_id)
    payload = v.body()
    reason = v.req_str(payload, "cancel_reason", 1)
    coach_note = v.free_text(payload, "coach_note")
    # Only COACH_CANCELLED is ever accepted from a client; the other two reasons are
    # written exclusively by cascades.
    if reason != "COACH_CANCELLED":
        fail("ERR_INVALID_REQUEST", "Field 'cancel_reason' must be COACH_CANCELLED.")
    if record["block_status"] != "SCHEDULED":
        fail("ERR_BLOCK_NOT_SCHEDULED")
    record["block_status"] = "CANCELLED"
    record["cancel_reason"] = "COACH_CANCELLED"
    if coach_note is not None:
        record["coach_note"] = coach_note
    db.touch(record)
    return response.object_response(ser.practice_block(record))

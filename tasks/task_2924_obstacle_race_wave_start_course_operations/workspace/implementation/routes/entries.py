"""Entries (PRD 3.5, 3.7, 3.8): the bag-check line, the finish and the protest cycle."""

from flask import Blueprint, g

import auth
import db
import validation
from errors import fail
from routes import common
from services import calc, results

bp = Blueprint("entries", __name__)

CHECKIN_ALLOWED_RELEASE_STATUSES = ("SCHEDULED", "HELD", "RELEASED")


@bp.get("/ocr/entries")
def list_entries():
    auth.require(
        auth.RACE_DIRECTOR, auth.SITE_OPS_LEAD, auth.SAFETY_OFFICER, auth.OBSTACLE_MARSHAL
    )
    wave_id = validation.query_str("wave_id")
    participant_id = validation.query_str("participant_id")
    progress_status = validation.query_enum("progress_status", validation.PROGRESS_STATUSES)
    result_status = validation.query_enum("result_status", validation.RESULT_STATUSES)
    disputed_attempt_id = validation.query_str("disputed_attempt_id")
    rows = db.all_rows("entries")
    if wave_id is not None:
        rows = [r for r in rows if r["wave_id"] == wave_id]
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if progress_status is not None:
        rows = [r for r in rows if r["progress_status"] == progress_status]
    if result_status is not None:
        rows = [r for r in rows if r["result_status"] == result_status]
    if disputed_attempt_id is not None:
        rows = [r for r in rows if r["disputed_attempt_id"] == disputed_attempt_id]
    return common.listing(rows)


@bp.get("/ocr/entries/<entry_id>")
def read_entry(entry_id):
    auth.require(
        auth.RACE_DIRECTOR,
        auth.SITE_OPS_LEAD,
        auth.SAFETY_OFFICER,
        auth.OBSTACLE_MARSHAL,
        auth.PARTICIPANT,
    )
    entry = validation.path_entry(entry_id)
    # Rung 6: a Participant reads only their own entry.
    if g.role == auth.PARTICIPANT and entry["participant_id"] != g.user_id:
        fail("ERR_NOT_ENTRY_OWNER", "Entry %s belongs to another participant." % entry["id"])
    return common.ok(entry)


@bp.post("/ocr/entries/<entry_id>/check-in")
def check_in_entry(entry_id):
    auth.require(auth.SITE_OPS_LEAD, auth.RACE_DIRECTOR)
    entry = validation.path_entry(entry_id)
    wave = common.wave_of(entry)
    participant = common.participant_of(entry)
    payload = validation.body()
    bag_tag_code = validation.field_str(payload, "bag_tag_code", 1)
    offset = validation.field_int(payload, "chip_start_offset_seconds", minimum=0)

    # Rung 9: entry state, then the roster dimension, then the start-line dimension.
    if entry["progress_status"] != "REGISTERED":
        fail("ERR_ENTRY_STATE_INVALID", "Entry %s reads %s." % (entry["id"], entry["progress_status"]))
    if wave["roster_status"] == "SEALED":
        fail("ERR_ROSTER_CLOSED", "Roster of heat %s is sealed." % wave["id"])
    if wave["release_status"] not in CHECKIN_ALLOWED_RELEASE_STATUSES:
        fail("ERR_WAVE_STATE_INVALID", "Heat %s reads %s." % (wave["id"], wave["release_status"]))

    # Rung 14: only a CLEARED human may take the start line.
    if participant["clearance_status"] != "CLEARED":
        fail(
            "ERR_PARTICIPANT_NOT_CLEARED",
            "Participant %s reads %s." % (participant["id"], participant["clearance_status"]),
        )

    with db.mutation(entry) as row:
        row["bag_tag_code"] = bag_tag_code
        row["chip_start_offset_seconds"] = offset
        row["progress_status"] = "CHECKED_IN"
    return common.ok(entry)


@bp.post("/ocr/entries/<entry_id>/reassign-wave")
def reassign_entry(entry_id):
    auth.require(auth.RACE_DIRECTOR)
    entry = validation.path_entry(entry_id)
    source = common.wave_of(entry)
    payload = validation.body()
    target_wave_id = validation.field_id(payload, "target_wave_id")

    # Rung 5.
    target = validation.fk_wave(target_wave_id)

    # Rung 9: only a still-registered entry moves, and both rosters must be OPEN.
    if entry["progress_status"] != "REGISTERED":
        fail("ERR_ENTRY_STATE_INVALID", "Entry %s reads %s." % (entry["id"], entry["progress_status"]))
    if source["roster_status"] != "OPEN":
        fail("ERR_ROSTER_CLOSED", "Roster of heat %s reads %s." % (source["id"], source["roster_status"]))
    if target["roster_status"] != "OPEN":
        fail("ERR_ROSTER_CLOSED", "Roster of heat %s reads %s." % (target["id"], target["roster_status"]))

    # Rung 10: same course and same division.
    if target["course_id"] != source["course_id"] or target["division_id"] != source["division_id"]:
        fail(
            "ERR_WAVE_COURSE_MISMATCH",
            "Heat %s is not on the same course carrying the same division." % target["id"],
        )

    # Rung 31: the receiving heat must have room.
    if int(target["assigned_count"]) + 1 > int(target["capacity"]):
        fail(
            "ERR_WAVE_CAPACITY_EXCEEDED",
            "Heat %s carries %d of %d entries."
            % (target["id"], int(target["assigned_count"]), int(target["capacity"])),
        )

    with db.mutation(entry) as row:
        row["wave_id"] = target["id"]
    common.recount_wave(source)
    common.recount_wave(target)
    return common.ok(entry)


@bp.post("/ocr/entries/<entry_id>/finish")
def finish_entry(entry_id):
    auth.require(auth.RACE_DIRECTOR, auth.OBSTACLE_MARSHAL)
    entry = validation.path_entry(entry_id)
    wave = common.wave_of(entry)

    if wave["release_status"] != "STARTED":
        fail("ERR_ENTRY_STATE_INVALID", "Heat %s reads %s." % (wave["id"], wave["release_status"]))
    if entry["progress_status"] != "STARTED":
        fail("ERR_ENTRY_STATE_INVALID", "Entry %s reads %s." % (entry["id"], entry["progress_status"]))

    with db.mutation(entry) as row:
        row["finish_recorded_utc"] = db.now()
        row["progress_status"] = "FINISHED"
        results.apply_provisional_reading(row, wave)
        if row["result_status"] == "PENDING":
            row["result_status"] = "PROVISIONAL"
    return common.ok(entry)


@bp.post("/ocr/entries/<entry_id>/protests")
def file_protest(entry_id):
    auth.require(auth.PARTICIPANT)
    entry = validation.path_entry(entry_id)
    payload = validation.body()
    disputed_attempt_id = validation.field_id(payload, "disputed_attempt_id")
    validation.field_str(payload, "reason", 1)

    # Rung 5: the attempt must sit on this very entry's card.
    validation.fk_attempt(disputed_attempt_id, entry_id=entry["id"])

    # Rung 6: only the owner protests.
    if entry["participant_id"] != g.user_id:
        fail("ERR_NOT_ENTRY_OWNER", "Entry %s belongs to another participant." % entry["id"])

    # Rung 9: protestable state, then the two-round ceiling.
    if entry["result_status"] != "PROVISIONAL":
        fail(
            "ERR_ENTRY_NOT_PROTESTABLE",
            "Entry %s reads result_status %s." % (entry["id"], entry["result_status"]),
        )
    if int(entry["protest_rounds"]) >= calc.MAX_PROTEST_ROUNDS:
        fail(
            "ERR_PROTEST_ROUNDS_EXHAUSTED",
            "Entry %s already carries %d adjudicated rounds." % (entry["id"], int(entry["protest_rounds"])),
        )

    with db.mutation(entry) as row:
        row["disputed_attempt_id"] = disputed_attempt_id
        row["result_status"] = "UNDER_PROTEST"
    return common.ok(entry)


@bp.post("/ocr/entries/<entry_id>/adjudications")
def adjudicate_protest(entry_id):
    auth.require(auth.RACE_DIRECTOR)
    entry = validation.path_entry(entry_id)
    wave = common.wave_of(entry)
    payload = validation.body()
    outcome = validation.field_enum(payload, "outcome", validation.ADJUDICATION_OUTCOMES)
    expected_version = validation.field_int(payload, "expected_entry_version")
    validation.field_str(payload, "note", min_len=0, default=None)

    disputed = db.get("attempts", entry["disputed_attempt_id"])

    # Rung 7: the marshal who wrote the outcome may not rule on the complaint.
    if disputed is not None and disputed["recorded_by_user_id"] == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "Operator %s recorded the disputed attempt." % g.user_id,
        )

    # Rung 8: the expected-version guard.
    if expected_version != int(entry["version"]):
        fail(
            "ERR_STALE_ENTRY_VERSION",
            "expected_entry_version %s does not match version %s."
            % (expected_version, entry["version"]),
        )

    # Rung 9: only an open protest admits a ruling.
    if entry["result_status"] != "UNDER_PROTEST":
        fail("ERR_ENTRY_STATE_INVALID", "Entry %s reads %s." % (entry["id"], entry["result_status"]))

    with db.mutation(entry) as row:
        row["protest_rounds"] = int(row["protest_rounds"]) + 1
        if outcome == "UPHELD_ADJUSTED":
            voided = list(row.get("voided_attempt_ids") or [])
            if row["disputed_attempt_id"] is not None:
                voided.append(row["disputed_attempt_id"])
            row["voided_attempt_ids"] = voided
            row["result_status"] = "PROVISIONAL"
            results.apply_official_reading(row, wave)
        elif outcome == "DENIED_OFFICIAL":
            row["result_status"] = "OFFICIAL"
            results.apply_official_reading(row, wave)
        else:
            row["result_status"] = "DISQUALIFIED"
            row["dq_reason"] = "ADJUDICATED_DQ"
    return common.ok(entry)


@bp.post("/ocr/entries/<entry_id>/attempts")
def record_attempt(entry_id):
    auth.require(auth.OBSTACLE_MARSHAL, auth.RACE_DIRECTOR)
    entry = validation.path_entry(entry_id)
    wave = common.wave_of(entry)
    division = common.division_of(wave)
    payload = validation.body()
    obstacle_id = validation.field_id(payload, "obstacle_id")
    outcome = validation.field_enum(payload, "outcome", validation.ATTEMPT_OUTCOMES)

    # Rung 5: the station must stand on the entry's own course.
    obstacle = validation.fk_obstacle(obstacle_id, course_id=wave["course_id"])

    # Rung 9.
    if entry["progress_status"] != "STARTED":
        fail("ERR_ENTRY_STATE_INVALID", "Entry %s reads %s." % (entry["id"], entry["progress_status"]))

    # Rung 15: marshaling truth cuts both ways.
    if outcome == "SKIPPED_UNMARSHALED":
        if obstacle["staffing_state"] != "UNSTAFFED":
            fail(
                "ERR_OBSTACLE_MARSHALED",
                "Obstacle %s reads %s." % (obstacle["id"], obstacle["staffing_state"]),
            )
    elif obstacle["staffing_state"] == "UNSTAFFED":
        fail("ERR_OBSTACLE_UNMARSHALED", "Obstacle %s has no confirmed marshal." % obstacle["id"])

    # Rung 17: either authority can veto a bypass.
    if outcome == "BYPASSED":
        if obstacle["bypass_mode"] == "MANDATORY":
            fail("ERR_BYPASS_NOT_ALLOWED", "Obstacle %s is mandatory." % obstacle["id"])
        if division is not None and division["bypass_policy"] == "MANDATORY_COMPLETION":
            fail("ERR_BYPASS_NOT_ALLOWED", "This division mandates completion.")

    attempt = db.insert(
        "attempts",
        {
            "entry_id": entry["id"],
            "obstacle_id": obstacle["id"],
            "outcome": outcome,
            "recorded_at": db.now(),
            "recorded_by_user_id": g.user_id,
            "recorded_by_role": g.role,
            "provisional_penalty_seconds": results.attempt_provisional_penalty(outcome, obstacle),
            "obstacle_staffing_state_at_record": obstacle["staffing_state"],
        },
        versioned=False,
    )

    with db.mutation(entry) as row:
        results.apply_provisional_penalty(row)
        if (
            outcome == "BYPASSED"
            and division is not None
            and division["bypass_policy"] == "DQ_ON_BYPASS"
            and row["result_status"] == "PENDING"
        ):
            row["result_status"] = "DISQUALIFIED"
            row["dq_reason"] = "BYPASS_IN_DQ_DIVISION"

    return common.created(attempt)


@bp.get("/ocr/entries/<entry_id>/attempts")
def list_entry_attempts(entry_id):
    auth.require(
        auth.RACE_DIRECTOR,
        auth.SITE_OPS_LEAD,
        auth.SAFETY_OFFICER,
        auth.OBSTACLE_MARSHAL,
        auth.PARTICIPANT,
    )
    entry = validation.path_entry(entry_id)
    outcome = validation.query_enum("outcome", validation.ATTEMPT_OUTCOMES)
    rows = calc.attempts_of_entry(entry["id"])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return common.listing(rows)

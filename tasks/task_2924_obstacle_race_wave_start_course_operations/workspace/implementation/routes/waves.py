"""Heats (PRD 3.4 and 3.6): the wave grid and the two orthogonal state dimensions."""

from flask import Blueprint

import auth
import db
import validation
from errors import fail
from routes import common
from services import calc, cascade, results

bp = Blueprint("waves", __name__)


@bp.post("/ocr/courses/<course_id>/waves")
def schedule_wave(course_id):
    auth.require(auth.RACE_DIRECTOR)
    course = validation.path_course(course_id)
    venue = common.venue_of(course)
    payload = validation.body()
    division_id = validation.field_id(payload, "division_id")
    wave_code = validation.field_str(payload, "wave_code", 1)
    scheduled_start = validation.field_datetime(payload, "scheduled_start_utc")
    capacity = validation.field_int(payload, "capacity", minimum=1)

    # Rung 5 then rung 9.
    validation.fk_division(division_id)
    common.require_venue_open(venue)

    # Rung 19: the nightly quiet window, only when an application governs.
    permit = calc.governing_permit(venue["id"])
    if permit is not None:
        if calc.in_quiet_window(
            scheduled_start.hour,
            int(permit["quiet_hours_start_hour_utc"]),
            int(permit["quiet_hours_end_hour_utc"]),
        ):
            fail(
                "ERR_QUIET_HOURS_VIOLATION",
                "Hour %d falls inside the nightly quiet window." % scheduled_start.hour,
            )

    # Rung 21: the shared start corral is an aggregate-capacity budget.
    load = calc.corral_occupancy_load(course, scheduled_start) + capacity
    if load > int(course["corral_throughput_capacity"]):
        fail(
            "ERR_CORRAL_WINDOW_CONFLICT",
            "Corral occupancy %d exceeds the budget of %d."
            % (load, int(course["corral_throughput_capacity"])),
        )

    # Rung 22: wave_code is unique among the heats of this course.
    for peer in calc.waves_of_course(course["id"]):
        if peer["wave_code"] == wave_code:
            fail("ERR_UNIQUENESS_CONFLICT", "wave_code %s is already used here." % wave_code)

    # Rung 30: the paper design ceiling on a 15-minute grid.
    ceiling = calc.max_wave_capacity_design(course)
    if capacity > ceiling:
        fail(
            "ERR_DESIGN_CAPACITY_EXCEEDED",
            "Capacity %d exceeds the design ceiling of %d." % (capacity, ceiling),
        )

    row = db.insert(
        "waves",
        {
            "course_id": course["id"],
            "division_id": division_id,
            "wave_code": wave_code,
            "scheduled_start_utc": scheduled_start,
            "capacity": capacity,
            "release_status": "SCHEDULED",
            "roster_status": "OPEN",
            "assigned_count": 0,
            "hold_reason": None,
            "actual_start_utc": None,
            "closed_at_utc": None,
        },
    )

    with db.mutation(course) as parent:
        calc.apply_scheduled_capacity(parent)
        calc.apply_readiness(parent)

    return common.created(row)


@bp.get("/ocr/waves")
def list_waves():
    auth.require(*auth.ALL_ROLES)
    course_id = validation.query_str("course_id")
    division_id = validation.query_str("division_id")
    release_status = validation.query_enum("release_status", validation.RELEASE_STATUSES)
    roster_status = validation.query_enum("roster_status", validation.ROSTER_STATUSES)
    rows = db.all_rows("waves")
    if course_id is not None:
        rows = [r for r in rows if r["course_id"] == course_id]
    if division_id is not None:
        rows = [r for r in rows if r["division_id"] == division_id]
    if release_status is not None:
        rows = [r for r in rows if r["release_status"] == release_status]
    if roster_status is not None:
        rows = [r for r in rows if r["roster_status"] == roster_status]
    return common.listing(rows)


@bp.get("/ocr/waves/<wave_id>")
def read_wave(wave_id):
    auth.require(*auth.ALL_ROLES)
    wave = validation.path_wave(wave_id)
    return common.ok(wave)


@bp.post("/ocr/waves/<wave_id>/hold")
def hold_wave(wave_id):
    auth.require(auth.SAFETY_OFFICER, auth.RACE_DIRECTOR)
    wave = validation.path_wave(wave_id)
    course = common.course_of(wave)
    payload = validation.body()
    held = validation.field_bool(payload, "held")
    reason = validation.field_str(payload, "reason", min_len=0, default=None)

    if held:
        if wave["release_status"] != "SCHEDULED":
            fail(
                "ERR_WAVE_STATE_INVALID",
                "A %s heat cannot be held." % wave["release_status"],
            )
        with db.mutation(wave) as row:
            row["release_status"] = "HELD"
            row["hold_reason"] = reason
    else:
        if wave["release_status"] != "HELD":
            fail(
                "ERR_WAVE_STATE_INVALID",
                "A %s heat cannot be returned to the schedule." % wave["release_status"],
            )
        # Rung 9 course state, then rung 12 readiness posture.
        if course["status"] not in ("VALIDATED", "PUBLISHED"):
            fail("ERR_COURSE_STATE_INVALID", "Course %s reads %s." % (course["id"], course["status"]))
        if course["readiness_posture"] != "OPEN":
            fail(
                "ERR_COURSE_UNSAFE",
                "Course %s reads readiness %s." % (course["id"], course["readiness_posture"]),
            )
        with db.mutation(wave) as row:
            row["release_status"] = "SCHEDULED"
            row["hold_reason"] = None

    return common.ok(wave)


@bp.post("/ocr/waves/<wave_id>/lock-roster")
def lock_roster(wave_id):
    auth.require(auth.RACE_DIRECTOR)
    wave = validation.path_wave(wave_id)
    if wave["roster_status"] != "OPEN":
        fail("ERR_WAVE_STATE_INVALID", "Roster is already %s." % wave["roster_status"])
    with db.mutation(wave) as row:
        row["roster_status"] = "LOCKED"
    return common.ok(wave)


@bp.post("/ocr/waves/<wave_id>/release")
def release_wave(wave_id):
    auth.require(auth.RACE_DIRECTOR)
    wave = validation.path_wave(wave_id)
    course = common.course_of(wave)

    # Rung 9: the two state refusals of the start line.
    if wave["release_status"] != "SCHEDULED":
        fail(
            "ERR_WAVE_NOT_RELEASABLE",
            "A %s heat cannot be released." % wave["release_status"],
        )
    if wave["roster_status"] == "OPEN":
        fail("ERR_WAVE_ROSTER_NOT_LOCKED", "The roster of heat %s is still open." % wave["id"])

    # Rung 10: the course must be published.
    if course["status"] != "PUBLISHED":
        fail("ERR_COURSE_NOT_PUBLISHED", "Course %s reads %s." % (course["id"], course["status"]))

    # Rung 11: medical coverage scales with the scheduled load.
    required_medics = calc.medics_required(course)
    if int(course["medic_headcount"]) < required_medics:
        fail(
            "ERR_MEDICAL_COVERAGE_INSUFFICIENT",
            "%d medic(s) confirmed against %d required."
            % (int(course["medic_headcount"]), required_medics),
        )

    # Rung 12: the safety gate.
    if course["readiness_posture"] != "OPEN":
        fail(
            "ERR_COURSE_UNSAFE",
            "Course %s reads readiness %s." % (course["id"], course["readiness_posture"]),
        )

    # Rung 32 then rung 33: the live ceiling precedes the empty-roster edge.
    live_ceiling = calc.max_wave_capacity_live(course)
    if int(wave["capacity"]) > live_ceiling:
        fail(
            "ERR_BOTTLENECK_CAPACITY_EXCEEDED",
            "Capacity %d exceeds the live ceiling of %d." % (int(wave["capacity"]), live_ceiling),
        )
    if int(wave["assigned_count"]) == 0:
        fail("ERR_WAVE_ROSTER_EMPTY", "Heat %s carries no entries." % wave["id"])

    with db.mutation(wave) as row:
        row["release_status"] = "RELEASED"
    return common.ok(wave)


@bp.post("/ocr/waves/<wave_id>/start")
def start_wave(wave_id):
    auth.require(auth.RACE_DIRECTOR)
    wave = validation.path_wave(wave_id)
    course = common.course_of(wave)
    division = common.division_of(wave)

    if wave["release_status"] != "RELEASED":
        fail("ERR_WAVE_STATE_INVALID", "A %s heat cannot be started." % wave["release_status"])

    # Rung 12: readiness must still read OPEN at the gun.
    if course["readiness_posture"] != "OPEN":
        fail(
            "ERR_COURSE_UNSAFE",
            "Course %s reads readiness %s." % (course["id"], course["readiness_posture"]),
        )

    entries = calc.entries_of_wave(wave["id"])

    # Rung 18: every team on the grid must field its minimum of checked-in runners.
    if division is not None and division["division_type"] == "TEAM":
        codes = []
        for entry in entries:
            code = entry.get("team_code")
            if code is not None and code not in codes:
                codes.append(code)
        for code in codes:
            checked_in = len(
                [
                    e
                    for e in entries
                    if e.get("team_code") == code and e["progress_status"] == "CHECKED_IN"
                ]
            )
            if checked_in < int(division["team_size_min"]):
                fail(
                    "ERR_TEAM_INCOMPLETE",
                    "Team %s has %d checked-in entries against %d required."
                    % (code, checked_in, int(division["team_size_min"])),
                )

    gun = db.now()
    with db.mutation(wave) as row:
        row["release_status"] = "STARTED"
        row["actual_start_utc"] = gun
        if row["roster_status"] == "LOCKED":
            row["roster_status"] = "SEALED"

    for entry in entries:
        if entry["progress_status"] == "CHECKED_IN":
            with db.mutation(entry) as row:
                row["progress_status"] = "STARTED"
                row["chip_start_utc"] = db.plus_seconds(
                    gun, int(row["chip_start_offset_seconds"])
                )
        elif entry["progress_status"] == "REGISTERED":
            with db.mutation(entry) as row:
                row["progress_status"] = "DNS"
                row["result_status"] = "NOT_CLASSIFIED"

    return common.ok(wave)


@bp.post("/ocr/waves/<wave_id>/close")
def close_wave(wave_id):
    auth.require(auth.RACE_DIRECTOR)
    wave = validation.path_wave(wave_id)
    course = common.course_of(wave)

    if wave["release_status"] != "STARTED":
        fail("ERR_WAVE_STATE_INVALID", "A %s heat cannot be closed." % wave["release_status"])

    closed_at = db.now()
    with db.mutation(wave) as row:
        row["release_status"] = "CLOSED"
        row["closed_at_utc"] = closed_at

    for entry in calc.entries_of_wave(wave["id"]):
        if entry["progress_status"] == "STARTED":
            with db.mutation(entry) as row:
                row["progress_status"] = "DNF"
                row["result_status"] = "NOT_CLASSIFIED"
        elif entry["result_status"] == "PROVISIONAL":
            with db.mutation(entry) as row:
                row["result_status"] = "OFFICIAL"
                results.apply_official_reading(row, wave)

    # The close bubbles up: PUBLISHED -> COMPLETED once no heat remains open.
    cascade.close_bubble_up(course)

    return common.ok(wave)


@bp.post("/ocr/waves/<wave_id>/entries")
def register_entry(wave_id):
    auth.require(auth.SITE_OPS_LEAD, auth.RACE_DIRECTOR)
    wave = validation.path_wave(wave_id)
    division = common.division_of(wave)
    payload = validation.body()
    participant_id = validation.field_id(payload, "participant_id")
    bib_number = validation.field_int(payload, "bib_number", minimum=1)
    team_code = validation.field_str(payload, "team_code", min_len=1, default=None)

    # Rung 5.
    participant = validation.fk_participant(participant_id)

    # Rung 9: registration is only accepted while the roster is OPEN.
    if wave["roster_status"] != "OPEN":
        fail("ERR_ROSTER_CLOSED", "Roster of heat %s reads %s." % (wave["id"], wave["roster_status"]))

    # Rung 13.
    if not participant["waiver_signed"]:
        fail("ERR_WAIVER_REQUIRED", "Participant %s has not signed the waiver." % participant["id"])

    # Rung 16: the division's shape rules.
    entries = calc.entries_of_wave(wave["id"])
    if division is not None:
        if division["division_type"] == "TEAM":
            if team_code is None:
                fail("ERR_DIVISION_RULE_VIOLATION", "A TEAM division requires team_code.")
            peers = len([e for e in entries if e.get("team_code") == team_code])
            if peers + 1 > int(division["team_size_max"]):
                fail(
                    "ERR_DIVISION_RULE_VIOLATION",
                    "Team %s already holds %d of %d entries."
                    % (team_code, peers, int(division["team_size_max"])),
                )
        elif team_code is not None:
            fail("ERR_DIVISION_RULE_VIOLATION", "A non-TEAM division forbids team_code.")

    # Rung 22: bib_number is unique per heat.
    for peer in entries:
        if int(peer["bib_number"]) == bib_number:
            fail("ERR_BIB_NUMBER_TAKEN", "Bib %d is already issued in this heat." % bib_number)

    # Rung 26: age is a pure calendar-year difference.
    if division is not None:
        age = calc.age_at_wave(participant, wave)
        if age < int(division["min_age"]):
            fail(
                "ERR_AGE_INELIGIBLE",
                "Age %d is below the division minimum of %d." % (age, int(division["min_age"])),
            )

    # Rung 31: the heat must have room.
    if int(wave["assigned_count"]) + 1 > int(wave["capacity"]):
        fail(
            "ERR_WAVE_CAPACITY_EXCEEDED",
            "Heat %s carries %d of %d entries."
            % (wave["id"], int(wave["assigned_count"]), int(wave["capacity"])),
        )

    row = db.insert(
        "entries",
        {
            "wave_id": wave["id"],
            "participant_id": participant["id"],
            "disputed_attempt_id": None,
            "bib_number": bib_number,
            "team_code": team_code,
            "bag_tag_code": None,
            "chip_start_offset_seconds": 0,
            "chip_start_utc": None,
            "finish_recorded_utc": None,
            "progress_status": "REGISTERED",
            "result_status": "PENDING",
            "provisional_penalty_seconds": 0,
            "provisional_elapsed_seconds": None,
            "official_penalty_seconds": 0,
            "official_elapsed_seconds": None,
            "protest_rounds": 0,
            "voided_attempt_ids": [],
            "dq_reason": None,
        },
    )
    common.recount_wave(wave)
    return common.created(row)

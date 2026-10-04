"""Route handlers: workout groups, field sessions, group assignments and
throwing programs."""

from datetime import timedelta

import rules as K
import state as S
from core import (ApiError, ERR_INVALID_STATE, ERR_MEDICAL_CLEARANCE_REQUIRED,
                  bad, fmt, new_record, optional_int, parse_dt, require_enum,
                  require_int, require_str, touch, upper_snake)
from store import db


# ---------------------------------------------------------------------------
def create_workout_group(env):
    complex_id = env["path"]["complex_id"]
    complex_record = db.get("complexes", complex_id)
    if complex_record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    body = env["body"]
    if body.get("complex_id") not in (None, complex_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "complex_id does not match the path.")
    group_name = require_str(body, "group_name")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "complex_id": complex_id,
        "roster_bucket": require_enum(body, "roster_bucket", ("MAJOR", "MINOR")),
        "group_name": group_name,
        "facility_kind": require_enum(body, "facility_kind",
                                      ("FIELD", "CLUBHOUSE", "TRAINING_ROOM")),
        "capacity_units": require_int(body, "capacity_units", 1),
        "assigned_units": 0,
        "assignment_group_tag": upper_snake(group_name),
        "group_status": "FORMING",
    })
    db.insert("workout_groups", record)
    return S.group_view(record)


def _group_or_404(group_id):
    record = db.get("workout_groups", group_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such workout group.")
    return record


def get_workout_group(env):
    return S.group_view(_group_or_404(env["path"]["group_id"]))


def list_complex_workout_groups(env):
    complex_id = env["path"]["complex_id"]
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    return [S.group_view(r) for r in db.find("workout_groups", complex_id=complex_id)]


def list_workout_groups(env):
    records = db.all("workout_groups")
    for key, value in (("complex_id", env["query"].get("complex_id")),
                       ("roster_bucket", env["query"].get("roster_bucket")),
                       ("group_status", env["query"].get("group_status"))):
        if value:
            records = [r for r in records if r.get(key) == value]
    return [S.group_view(r) for r in records]


def publish_workout_group(env):
    record = _group_or_404(env["path"]["group_id"])
    body = env["body"]
    if body.get("expected_group_version") is not None:
        expected = body["expected_group_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise bad("expected_group_version must be an integer.")
        if expected != record["version"]:
            raise ApiError("ERR_STALE_VERSION", "The workout group has advanced.")
    if record["group_status"] != "FORMING":
        raise ApiError(ERR_INVALID_STATE, "The workout group is not forming.")
    S.recompute_workout_group(record)
    if record["assigned_units"] > record["capacity_units"]:
        raise ApiError("ERR_GROUP_CAPACITY_EXCEEDED", "The group is over capacity.")
    complex_record = db.get("complexes", record["complex_id"])
    if complex_record is not None and complex_record["field_maintenance_status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "The owning complex is closed for field work.")
    for assignment in S.assignments_of_group(record["id"]):
        if assignment["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        program = S.program_for_assignment(assignment["id"])
        if program is not None and program["requirement_status"] == "UNMET":
            raise ApiError("ERR_THROW_REQUIREMENT_UNMET",
                           "A member pitcher's throwing requirement is unmet.")
    record["group_status"] = "PUBLISHED"
    touch(record, db.clock)
    if complex_record is not None:
        S.recompute_complex(complex_record)
    return S.group_view(record)


def disband_workout_group(env):
    record = _group_or_404(env["path"]["group_id"])
    if record["group_status"] != "FORMING":
        raise ApiError(ERR_INVALID_STATE, "The workout group is not forming.")
    record["group_status"] = "DISBANDED"
    _disband_effects(record)
    touch(record, db.clock)
    return S.group_view(record)


def _disband_effects(group):
    member_ids = set()
    for assignment in S.assignments_of_group(group["id"]):
        member_ids.add(assignment["player_id"])
        if assignment["assignment_status"] in ("PROVISIONAL", "ACTIVE"):
            assignment["assignment_status"] = "WITHDRAWN"
            touch(assignment, db.clock)
    S.recompute_workout_group(group)
    complex_record = db.get("complexes", group["complex_id"])
    if complex_record is not None:
        S.recompute_complex(complex_record)
    for player_id in member_ids:
        profile = S.profile_of(player_id)
        if profile is not None:
            S.recompute_profile(profile)
        S.detach_roster_from_camp(player_id)


# ---------------------------------------------------------------------------
def create_workout_group_session(env):
    group = _group_or_404(env["path"]["group_id"])
    body = env["body"]
    if body.get("workout_group_id") not in (None, group["id"]):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "workout_group_id does not match the path.")
    session_date = parse_dt(body.get("session_date"), "session_date")
    session_end = parse_dt(body.get("session_end_datetime"), "session_end_datetime")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "workout_group_id": group["id"],
        "session_date": fmt(session_date),
        "session_end_datetime": fmt(session_end),
        "session_kind": require_enum(body, "session_kind",
                                     ("BULLPEN", "CATCH_PLAY", "LIVE_BP", "DEFENSE")),
        "field_units": require_int(body, "field_units", 1),
        "session_status": "SCHEDULED",
    })
    db.insert("workout_group_sessions", record)
    for player_id in _member_player_ids(group["id"]):
        profile = S.profile_of(player_id)
        if profile is not None:
            S.recompute_profile(profile)
    return S.plain(record)


def _member_player_ids(group_id):
    return {a["player_id"] for a in S.assignments_of_group(group_id)
            if a["assignment_status"] in ("PROVISIONAL", "ACTIVE")}


def list_group_sessions(env):
    group = _group_or_404(env["path"]["group_id"])
    return [S.plain(r) for r in db.find("workout_group_sessions",
                                        workout_group_id=group["id"])]


def list_workout_group_sessions(env):
    records = db.all("workout_group_sessions")
    group_id = env["query"].get("workout_group_id")
    if group_id:
        records = [r for r in records if r["workout_group_id"] == group_id]
    kind = env["query"].get("session_kind")
    if kind:
        records = [r for r in records if r["session_kind"] == kind]
    return [S.plain(r) for r in records]


def get_workout_group_session(env):
    record = db.get("workout_group_sessions", env["path"]["session_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such session block.")
    return S.plain(record)


def publish_group_session(env):
    group = _group_or_404(env["path"]["group_id"])
    record = db.get("workout_group_sessions", env["path"]["session_id"])
    if record is None or record["workout_group_id"] != group["id"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such session block on this group.")
    if record["session_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "The session block is not scheduled.")
    record["session_status"] = "PUBLISHED"
    touch(record, db.clock)
    # The publication resolves the PHASE_3 -> PHASE_4 reconciliation lag.
    for assignment in S.assignments_of_group(group["id"]):
        if assignment["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        program = S.program_for_assignment(assignment["id"])
        profile = S.profile_of(assignment["player_id"])
        if program is not None and profile is not None and \
                program["program_phase"] in ("PHASE_4", "PHASE_LIVE"):
            if profile["rehab_program_phase"] != program["program_phase"]:
                profile["rehab_program_phase"] = program["program_phase"]
                touch(profile, db.clock)
        if profile is not None:
            S.recompute_profile(profile)
    return S.plain(record)


# ---------------------------------------------------------------------------
def create_group_assignment(env):
    group = _group_or_404(env["path"]["group_id"])
    body = env["body"]
    if "expected_group_version" not in body or body["expected_group_version"] is None:
        raise bad("expected_group_version is required.")
    expected = body["expected_group_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise bad("expected_group_version must be an integer.")
    if expected != group["version"]:
        raise ApiError("ERR_STALE_VERSION", "The workout group has advanced.")
    if body.get("workout_group_id") not in (None, group["id"]):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "workout_group_id does not match the path.")
    player_id = require_str(body, "player_id")
    if db.get("players", player_id) is None:
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "No such player.")
    roster_bucket = require_enum(body, "roster_bucket", ("MAJOR", "MINOR"))
    if roster_bucket != group["roster_bucket"]:
        raise ApiError("ERR_BUCKET_MISMATCH",
                       "The assignment bucket differs from the group's bucket.")
    S.recompute_workout_group(group)
    if group["assigned_units"] + 1 > group["capacity_units"]:
        raise ApiError("ERR_GROUP_CAPACITY_EXCEEDED", "The group is at capacity.")
    assignment_kind = require_enum(body, "assignment_kind", ("ACTIVE_WORKOUT", "REHAB"))
    record = new_record(db.new_id(), db.clock)
    record.update({
        "workout_group_id": group["id"],
        "player_id": player_id,
        "roster_bucket": roster_bucket,
        "assignment_kind": assignment_kind,
        "assignment_status": "PROVISIONAL",
        "assigned_at": fmt(db.clock),
        "withdrawal_reason": None,
    })
    db.insert("group_assignments", record)
    _after_assignment_change(group)
    return S.plain(record)


def _after_assignment_change(group):
    S.recompute_workout_group(group)
    group["version"] = group["version"] + 1
    group["updated_at"] = fmt(db.clock)
    complex_record = db.get("complexes", group["complex_id"])
    if complex_record is not None:
        S.recompute_complex(complex_record)
    # the profile's group counts are recomputed for every player holding a row
    # in this group, including a row the change just withdrew
    for assignment in S.assignments_of_group(group["id"]):
        profile = S.profile_of(assignment["player_id"])
        if profile is not None:
            S.recompute_profile(profile)
            S.detach_roster_from_camp(assignment["player_id"])


def _assignment_or_404(assignment_id):
    record = db.get("group_assignments", assignment_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such group assignment.")
    return record


def get_group_assignment(env):
    return S.plain(_assignment_or_404(env["path"]["assignment_id"]))


def list_group_assignments(env):
    records = db.all("group_assignments")
    for key, value in (("workout_group_id", env["query"].get("workout_group_id")),
                       ("player_id", env["query"].get("player_id")),
                       ("assignment_status", env["query"].get("assignment_status"))):
        if value:
            records = [r for r in records if r.get(key) == value]
    return [S.plain(r) for r in records]


def list_group_assignments_of_group(env):
    group = _group_or_404(env["path"]["group_id"])
    return [S.plain(r) for r in S.assignments_of_group(group["id"])]


def call_up_assignment(env):
    record = _assignment_or_404(env["path"]["assignment_id"])
    group = _group_or_404(record["workout_group_id"])
    player = db.get("players", record["player_id"])
    if record["assignment_status"] != "PROVISIONAL":
        raise ApiError(ERR_INVALID_STATE, "The assignment is not provisional.")
    if group["group_status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, "The owning group is not published.")
    if player is None or player["clearance_status"] != "CAMP_CLEARED":
        raise ApiError(ERR_MEDICAL_CLEARANCE_REQUIRED, "The player is not camp-cleared.")
    S.recompute_workout_group(group)
    if group["assigned_units"] > group["capacity_units"]:
        raise ApiError("ERR_GROUP_CAPACITY_EXCEEDED", "The group is at capacity.")
    for other in S.assignments_of_player(record["player_id"]):
        if other["id"] != record["id"] and other["assignment_status"] == "ACTIVE":
            raise ApiError("ERR_PLAYER_ALREADY_ASSIGNED",
                           "The player already holds an active assignment.")
    for member in S.assignments_of_group(group["id"]):
        if member["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        program = S.program_for_assignment(member["id"])
        if program is not None and program["requirement_status"] == "UNMET":
            raise ApiError("ERR_THROW_REQUIREMENT_UNMET",
                           "A member pitcher's throwing requirement is unmet.")
    record["assignment_status"] = "ACTIVE"
    touch(record, db.clock)
    _after_assignment_change(group)
    return S.plain(record)


def withdraw_assignment(env):
    record = _assignment_or_404(env["path"]["assignment_id"])
    group = _group_or_404(record["workout_group_id"])
    if record["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, "The assignment is already withdrawn.")
    was_provisional = record["assignment_status"] == "PROVISIONAL"
    if was_provisional:
        reason = require_str(env["body"], "withdrawal_reason")
        record["withdrawal_reason"] = reason
    record["assignment_status"] = "WITHDRAWN"
    touch(record, db.clock)
    _after_assignment_change(group)
    if was_provisional and group["assigned_units"] == 0 and \
            group["group_status"] == "FORMING":
        group["group_status"] = "DISBANDED"
        group["version"] = group["version"] + 1
        group["updated_at"] = fmt(db.clock)
    return S.plain(record)


# ---------------------------------------------------------------------------
def create_throw_program(env):
    assignment = _assignment_or_404(env["path"]["assignment_id"])
    body = env["body"]
    if body.get("group_assignment_id") not in (None, assignment["id"]):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND",
                       "group_assignment_id does not match the path.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "group_assignment_id": assignment["id"],
        "player_id": assignment["player_id"],
        "program_phase": "PHASE_1",
        "target_catch_play_throws": require_int(body, "target_catch_play_throws", 1),
        "target_bullpen_sessions": require_int(body, "target_bullpen_sessions", 1),
        "cumulative_throws": 0,
        "cumulative_bullpen_sessions": 0,
        "schedule_requirement_throws": 0,
        "requirement_status": "NOT_REQUIRED",
        "last_session_date": None,
        "last_game_scheduled_date": None,
    })
    db.insert("throw_programs", record)
    S.recompute_throw_program(record)
    profile = S.profile_of(assignment["player_id"])
    if profile is not None:
        profile["rehab_program_phase"] = "PHASE_1"
        S.recompute_profile(profile)
    return S.plain(record)


def _program_or_404(program_id):
    record = db.get("throw_programs", program_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such throwing program.")
    return record


def get_throw_program(env):
    record = _program_or_404(env["path"]["program_id"])
    S.recompute_throw_program(record)
    return S.plain(record)


def list_throw_programs(env):
    records = db.all("throw_programs")
    assignment_id = env["query"].get("group_assignment_id")
    if assignment_id:
        records = [r for r in records if r["group_assignment_id"] == assignment_id]
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    return [S.plain(r) for r in records]


def list_assignment_throw_programs(env):
    assignment = _assignment_or_404(env["path"]["assignment_id"])
    return [S.plain(r) for r in db.find("throw_programs",
                                        group_assignment_id=assignment["id"])]


def log_throw_session(env):
    program = _program_or_404(env["path"]["program_id"])
    body = env["body"]
    if body.get("throw_program_id") not in (None, program["id"]):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "throw_program_id does not match the path.")
    logged_at = parse_dt(body.get("logged_at"), "logged_at")
    kind = require_enum(body, "session_kind", ("CATCH_PLAY", "BULLPEN"))
    throws = optional_int(body, "play_catch_throws", 0, 0)
    if kind != "CATCH_PLAY" and throws:
        raise bad("play_catch_throws may only be supplied for a catch-play session.")
    existing = db.find("throw_program_sessions", throw_program_id=program["id"])
    sequence = 0
    for row in existing:
        sequence = max(sequence, row["session_sequence"])
    record = new_record(db.new_id(), db.clock)
    record.update({
        "throw_program_id": program["id"],
        "logged_at": fmt(logged_at),
        "session_sequence": sequence + 1,
        "session_kind": kind,
        "play_catch_throws": throws,
        "session_status": "LOGGED",
    })
    db.insert("throw_program_sessions", record)
    S.recompute_throw_program(program)
    _recompute_group_requirement(program)
    return S.plain(record)


def _recompute_group_requirement(program):
    assignment = db.get("group_assignments", program["group_assignment_id"])
    if assignment is None:
        return
    group = db.get("workout_groups", assignment["workout_group_id"])
    if group is None:
        return
    for member in S.assignments_of_group(group["id"]):
        other = S.program_for_assignment(member["id"])
        if other is not None and other["id"] != program["id"]:
            S.recompute_throw_program(other)


def list_program_sessions(env):
    program = _program_or_404(env["path"]["program_id"])
    return [S.plain(r) for r in S.sessions_of_program(program["id"])]


def list_throw_program_sessions(env):
    records = db.all("throw_program_sessions")
    program_id = env["query"].get("throw_program_id")
    if program_id:
        records = [r for r in records if r["throw_program_id"] == program_id]
    kind = env["query"].get("session_kind")
    if kind:
        records = [r for r in records if r["session_kind"] == kind]
    return [S.plain(r) for r in records]


def get_throw_program_session(env):
    record = db.get("throw_program_sessions", env["path"]["session_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such throwing-program session.")
    return S.plain(record)


def _mirror_phase(program, phase):
    profile = S.profile_of(program["player_id"])
    if profile is not None:
        profile["rehab_program_phase"] = phase
        touch(profile, db.clock)


def advance_phase(env):
    program = _program_or_404(env["path"]["program_id"])
    direction = require_enum(env["body"], "direction", ("ADVANCE", "REGRESS"))
    phase = program["program_phase"]

    if direction == "ADVANCE":
        if phase == "PHASE_1":
            if program["cumulative_throws"] < program["target_catch_play_throws"]:
                raise ApiError(ERR_INVALID_STATE, "The catch-play target is not met.")
            program["program_phase"] = "PHASE_2"
            S.recompute_throw_program(program)
            _mirror_phase(program, "PHASE_2")
        elif phase == "PHASE_2":
            if program["cumulative_bullpen_sessions"] < program["target_bullpen_sessions"]:
                raise ApiError(ERR_INVALID_STATE, "The bullpen target is not met.")
            program["program_phase"] = "PHASE_3"
            S.recompute_throw_program(program)
            _mirror_phase(program, "PHASE_3")
        elif phase == "PHASE_3":
            if program["requirement_status"] not in ("NOT_REQUIRED", "MET"):
                raise ApiError(ERR_INVALID_STATE, "The throwing requirement is unmet.")
            program["program_phase"] = "PHASE_4"
            S.recompute_throw_program(program)
            # Reconciliation lag: the profile mirror waits for a session publish.
        elif phase == "PHASE_4":
            player = db.get("players", program["player_id"])
            if program["requirement_status"] == "UNMET":
                raise ApiError(ERR_INVALID_STATE, "The throwing requirement is unmet.")
            if player is None or player["clearance_status"] != "CAMP_CLEARED":
                raise ApiError(ERR_MEDICAL_CLEARANCE_REQUIRED,
                               "The player is not camp-cleared.")
            program["program_phase"] = "PHASE_LIVE"
            S.recompute_throw_program(program)
            _mirror_phase(program, "PHASE_LIVE")
            if program["requirement_status"] == "MET":
                _cascade_live_assignment(program)
        else:
            raise ApiError(ERR_INVALID_STATE, "The program cannot advance from here.")
    else:
        if phase == "PHASE_2":
            if program["cumulative_throws"] >= program["target_catch_play_throws"]:
                raise ApiError(ERR_INVALID_STATE, "The catch-play target still holds.")
            program["program_phase"] = "PHASE_1"
            S.recompute_throw_program(program)
            _mirror_phase(program, "PHASE_1")
        elif phase == "PHASE_3":
            if program["requirement_status"] != "UNMET":
                raise ApiError(ERR_INVALID_STATE, "The requirement is not unmet.")
            program["program_phase"] = "PHASE_2"
            S.recompute_throw_program(program)
        else:
            raise ApiError(ERR_INVALID_STATE, "The program cannot regress from here.")

    touch(program, db.clock)
    return S.plain(program)


def _cascade_live_assignment(program):
    """CASCADE 2: the live advance seats the pitcher into a workout group."""
    current = db.get("group_assignments", program["group_assignment_id"])
    if current is None:
        return
    group = db.get("workout_groups", current["workout_group_id"])
    if group is None:
        return
    if group["group_status"] != "PUBLISHED":
        return
    S.recompute_workout_group(group)
    if group["assigned_units"] + 1 > group["capacity_units"]:
        return
    record = new_record(db.new_id(), db.clock)
    record.update({
        "workout_group_id": group["id"],
        "player_id": program["player_id"],
        "roster_bucket": group["roster_bucket"],
        "assignment_kind": "REHAB",
        "assignment_status": "PROVISIONAL",
        "assigned_at": fmt(db.clock),
        "withdrawal_reason": None,
    })
    db.insert("group_assignments", record)
    _after_assignment_change(group)


def shutdown_program(env):
    program = _program_or_404(env["path"]["program_id"])
    if program["program_phase"] != "PHASE_LIVE":
        raise ApiError(ERR_INVALID_STATE, "The program is not live.")
    program["program_phase"] = "SHUTDOWN"
    S.recompute_throw_program(program)
    program["requirement_status"] = "NOT_REQUIRED"
    _mirror_phase(program, "SHUTDOWN")
    for assignment in S.assignments_of_player(program["player_id"]):
        if assignment["assignment_status"] == "PROVISIONAL":
            assignment["assignment_status"] = "WITHDRAWN"
            touch(assignment, db.clock)
    for complex_record in db.all("complexes"):
        S.recompute_complex(complex_record)
    for roster_group in db.all("workout_groups"):
        S.recompute_workout_group(roster_group)
    profile = S.profile_of(program["player_id"])
    if profile is not None:
        S.recompute_profile(profile)
    touch(program, db.clock)
    return S.plain(program)


def reinstate_program(env):
    program = _program_or_404(env["path"]["program_id"])
    if program["program_phase"] != "SHUTDOWN":
        raise ApiError(ERR_INVALID_STATE, "The program is not shut down.")
    assignment = db.get("group_assignments", program["group_assignment_id"])
    if assignment is not None:
        group = db.get("workout_groups", assignment["workout_group_id"])
        if group is not None:
            for game in db.find("games", complex_id=group["complex_id"]):
                S.recompute_game(game)
                if game["gameday_status"] == "GAMEDAY":
                    raise ApiError(ERR_INVALID_STATE,
                                   "A program may not be reinstated on a gameday.")
    program["program_phase"] = "PHASE_1"
    program["cumulative_throws"] = 0
    program["cumulative_bullpen_sessions"] = 0
    S.recompute_throw_program(program)
    _mirror_phase(program, "PHASE_1")
    touch(program, db.clock)
    return S.plain(program)
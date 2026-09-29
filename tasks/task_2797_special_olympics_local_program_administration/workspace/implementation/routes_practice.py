"""Seasons, practice sessions, attendance and the practice-minute ledger."""
import math
from datetime import timedelta

from flask import Blueprint

import db
import derive
from core import (ATTENDANCE_COUNT_FRACTION, ATTENDANCE_STATUSES,
                  COACH_SESSION_BUFFER_MINUTES, GAMES_LEVELS,
                  MIN_QUALIFYING_SESSION_MINUTES, SESSION_STATUSES,
                  SESSION_VOID_REASON_CODES, SPORTS, auth, bad_request,
                  clock_date, clock_now, dec, fail, fmt_date, fmt_ts, get_body,
                  ok, paginate, parse_date, parse_dt, query_enum, query_str,
                  req_date_field, req_dt_field, req_enum, req_int, req_str)
from serialize import ser_attendance, ser_season, ser_session

bp = Blueprint("practice", __name__)

# ------------------------------------------------------------------ seasons ---


@bp.post("/programs/<rid>/seasons")
def create_season(rid):
    auth(["ProgramManager", "CompetitionDirector"])
    program = derive.require("programs", rid)
    body = get_body()
    sport = req_enum(body, "sport", SPORTS)
    season_name = req_str(body, "season_name", 3, 120)
    minimum_sessions = req_int(body, "practice_minimum_sessions", 0, 40)
    minimum_minutes = req_int(body, "practice_minimum_minutes", 0, 3000)
    registration_deadline = req_date_field(body, "registration_deadline")
    divisioning_date = req_date_field(body, "divisioning_date")
    competition_date = req_date_field(body, "competition_date")
    games_level = req_enum(body, "games_level", GAMES_LEVELS)
    entry_slot_budget = req_int(body, "entry_slot_budget", 1, 500)
    advancement_slots = req_int(body, "advancement_slots_per_division", 1, 8)
    if not (registration_deadline < divisioning_date < competition_date):
        fail("ERR_SEASON_DATE_ORDER", 400,
             "registration_deadline, divisioning_date and competition_date "
             "must be strictly increasing.")
    season = db.new_row("seasons", {
        "program_id": program["id"],
        "sport": sport,
        "season_name": season_name,
        "practice_minimum_sessions": minimum_sessions,
        "practice_minimum_minutes": minimum_minutes,
        "registration_deadline": fmt_date(registration_deadline),
        "divisioning_date": fmt_date(divisioning_date),
        "competition_date": fmt_date(competition_date),
        "games_level": games_level,
        "entry_slot_budget": entry_slot_budget,
        "advancement_slots_per_division": advancement_slots,
        "status": "PLANNING",
        "divisioning_run_count": 0,
        "entry_count": 0,
        "divisioned_entry_count": 0,
    })
    return ok(ser_season(season), 201)


@bp.get("/seasons/<rid>")
def get_season(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    season = derive.require("seasons", rid)
    return ok(ser_season(season))


@bp.post("/seasons/<rid>/open-practice")
def open_practice(rid):
    auth(["ProgramManager", "CompetitionDirector"])
    season = derive.require("seasons", rid)
    if season["status"] != "PLANNING":
        fail("ERR_SEASON_STATE_INVALID", 409,
             "Only a PLANNING season may have its practice window opened.")
    competition_date = parse_date(season["competition_date"])
    if clock_date() > competition_date:
        fail("ERR_SEASON_STATE_INVALID", 409,
             "This season's competition date has already passed.")
    program = derive.program_of_season(season)
    if program["certified_coach_count"] < 1:
        fail("ERR_PROGRAM_POSTURE_FROZEN", 409,
             "The program holds no live certified coach credential.")
    derive.posture_gate(program, "open_practice")
    db.apply_changes(season, {"status": "PRACTICE_OPEN"})
    return ok(ser_season(season))

# --------------------------------------------------------- practice sessions ---


def _body_fk(body, key, collection):
    value = body.get(key)
    if not isinstance(value, str) or value == "":
        bad_request("Field '%s' must be a resource id string." % key)
    return derive.require(collection, value)


def _ownership_gate(role, user_id, credential):
    """A Coach may only act on a credential they personally hold."""
    if role != "Coach":
        return
    if (credential["volunteer_id"] != user_id
            or credential["role_class"] != "COACH"
            or credential["status"] != "CERTIFIED"):
        fail("ERR_NOT_CREDENTIAL_OWNER", 403,
             "This coaching credential does not belong to the acting coach.")


@bp.get("/practice-sessions")
def list_sessions():
    auth(["ProgramManager", "CompetitionDirector", "Coach",
          "CredentialingOfficer"], write=False)
    season_id = query_str("season_id")
    credential_id = query_str("coach_credential_id")
    status = query_enum("status", SESSION_STATUSES)
    rows = list(db.sessions.values())
    if season_id:
        rows = [s for s in rows if s["season_id"] == season_id]
    if credential_id:
        rows = [s for s in rows if s["coach_credential_id"] == credential_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return paginate(rows, ser_session)


@bp.get("/practice-sessions/<rid>")
def get_session(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    session = derive.require("sessions", rid)
    return ok(ser_session(session))


@bp.post("/practice-sessions")
def create_session():
    role, user_id = auth(["ProgramManager", "Coach"])
    body = get_body()
    season = _body_fk(body, "season_id", "seasons")
    credential = _body_fk(body, "coach_credential_id", "credentials")
    scheduled_start = req_dt_field(body, "scheduled_start")
    duration_minutes = req_int(body, "duration_minutes", 30, 240)
    capacity_slots = req_int(body, "capacity_slots", 1, 60)
    _ownership_gate(role, user_id, credential)
    if season["status"] != "PRACTICE_OPEN":
        fail("ERR_SEASON_NOT_PRACTICE_OPEN", 409,
             "The season is not open for practice.")
    program = derive.program_of_season(season)
    derive.posture_gate(program, "session_create")
    if scheduled_start < clock_now():
        fail("ERR_SESSION_START_IN_PAST", 422,
             "scheduled_start may not fall before the logical clock.")
    scheduled_end = scheduled_start + timedelta(minutes=duration_minutes)
    buffer_delta = timedelta(minutes=COACH_SESSION_BUFFER_MINUTES)
    for other in db.sessions.values():
        if other["coach_credential_id"] != credential["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "HELD"):
            continue
        other_start = parse_dt(other["scheduled_start"])
        other_end = parse_dt(other["scheduled_end"])
        if other_start is None or other_end is None:
            continue
        if (scheduled_start < other_end + buffer_delta
                and other_start - buffer_delta < scheduled_end):
            fail("ERR_COACH_SESSION_OVERLAP", 409,
                 "This coaching credential already holds an overlapping "
                 "session.")
    if not derive.credential_is_live(credential, "COACH"):
        fail("ERR_COACH_CREDENTIAL_INVALID", 422,
             "coach_credential_id must name a live CERTIFIED COACH credential.")
    session = db.new_row("sessions", {
        "season_id": season["id"],
        "coach_credential_id": credential["id"],
        "scheduled_start": fmt_ts(scheduled_start),
        "duration_minutes": duration_minutes,
        "capacity_slots": capacity_slots,
        "scheduled_end": fmt_ts(scheduled_end),
        "counts_toward_minimum": duration_minutes >= MIN_QUALIFYING_SESSION_MINUTES,
        "recorded_attendance_count": 0,
        "status": "SCHEDULED",
        "void_reason_code": None,
    })
    return ok(ser_session(session), 201)


@bp.post("/practice-sessions/<rid>/cancel")
def cancel_session(rid):
    role, user_id = auth(["ProgramManager", "Coach"])
    session = derive.require("sessions", rid)
    body = get_body()
    void_reason_code = req_enum(body, "void_reason_code",
                                SESSION_VOID_REASON_CODES)
    credential = db.credentials.get(session["coach_credential_id"])
    if credential is not None:
        _ownership_gate(role, user_id, credential)
    if session["status"] not in ("SCHEDULED", "HELD"):
        fail("ERR_SESSION_NOT_OPEN_FOR_ATTENDANCE", 409,
             "This session is already voided.")
    affected = derive.void_session(session, void_reason_code)
    for athlete_id in affected:
        athlete = db.athletes.get(athlete_id)
        if athlete is not None:
            derive.recompute_athlete_ledger(athlete)
    derive.recompute_program(derive.program_of_session(session))
    return ok(ser_session(session))

# ------------------------------------------------------------- attendance ---


@bp.get("/practice-sessions/<rid>/attendance-records")
def list_session_attendance(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    session = derive.require("sessions", rid)
    status = query_enum("status", ATTENDANCE_STATUSES)
    rows = [r for r in db.attendance.values()
            if r["session_id"] == session["id"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_attendance)


@bp.get("/athletes/<rid>/attendance-records")
def list_athlete_attendance(rid):
    auth(["ProgramManager", "Coach", "CompetitionDirector"], write=False)
    athlete = derive.require("athletes", rid)
    status = query_enum("status", ATTENDANCE_STATUSES)
    season_id = query_str("season_id")
    rows = [r for r in db.attendance.values()
            if r["athlete_id"] == athlete["id"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if season_id:
        rows = [r for r in rows if r["season_id"] == season_id]
    return paginate(rows, ser_attendance)


@bp.post("/practice-sessions/<rid>/attendance-records")
def create_attendance(rid):
    role, user_id = auth(["ProgramManager", "Coach"])
    session = derive.require("sessions", rid)
    body = get_body()
    athlete = _body_fk(body, "athlete_id", "athletes")
    minutes_present = req_int(body, "minutes_present", 0, 240)
    if minutes_present > session["duration_minutes"]:
        bad_request("minutes_present may not exceed the session's "
                    "duration_minutes.")
    expected_version = req_int(body, "expected_session_version")
    credential = db.credentials.get(session["coach_credential_id"])
    if credential is not None:
        _ownership_gate(role, user_id, credential)
    if expected_version != session["version"]:
        fail("ERR_STALE_SESSION_VERSION", 412,
             "expected_session_version does not match the session's current "
             "version.")
    season = db.seasons[session["season_id"]]
    if season["status"] != "PRACTICE_OPEN":
        fail("ERR_SEASON_NOT_PRACTICE_OPEN", 409,
             "The season is not open for practice.")
    if session["status"] not in ("SCHEDULED", "HELD"):
        fail("ERR_SESSION_NOT_OPEN_FOR_ATTENDANCE", 409,
             "This session is not open for attendance.")
    program = derive.program_of_season(season)
    derive.posture_gate(program, "attendance_create")
    if athlete["medical_status"] not in ("CLEARED", "RESTRICTED"):
        fail("ERR_ATHLETE_MEDICAL_HOLD", 422,
             "The athlete's medical dimension does not clear them for a field "
             "of play.")
    if athlete["registration_status"] != "ACTIVE":
        fail("ERR_ATHLETE_NOT_ACTIVE", 422,
             "The athlete's registration is not ACTIVE.")
    start = parse_dt(session["scheduled_start"])
    end = parse_dt(session["scheduled_end"])
    if clock_now() < start:
        fail("ERR_ATTENDANCE_BEFORE_SESSION_START", 422,
             "The session has not begun yet.")
    for row in db.attendance.values():
        if row["athlete_id"] != athlete["id"]:
            continue
        if row["status"] not in ("COUNTED", "NOT_COUNTED"):
            continue
        if row["session_id"] == session["id"]:
            continue
        other = db.sessions.get(row["session_id"])
        if other is None or other["status"] not in ("SCHEDULED", "HELD"):
            continue
        other_start = parse_dt(other["scheduled_start"])
        other_end = parse_dt(other["scheduled_end"])
        if other_start is None or other_end is None:
            continue
        if start <= other_end and other_start <= end:
            fail("ERR_ATHLETE_SESSION_OVERLAP", 409,
                 "The athlete is already recorded on an overlapping session.")
    for row in db.attendance.values():
        if (row["session_id"] == session["id"]
                and row["athlete_id"] == athlete["id"]
                and row["status"] in ("COUNTED", "NOT_COUNTED")):
            fail("ERR_DUPLICATE_ATTENDANCE", 409,
                 "This athlete already has an attendance row on this session.")
    if session["recorded_attendance_count"] >= session["capacity_slots"]:
        fail("ERR_SESSION_CAPACITY_EXCEEDED", 409,
             "This session has no capacity slot left.")

    required_minutes = int(math.ceil(
        dec(session["duration_minutes"]) * ATTENDANCE_COUNT_FRACTION))
    qualifies = session["duration_minutes"] >= MIN_QUALIFYING_SESSION_MINUTES
    counted = qualifies and minutes_present >= required_minutes
    record = db.new_row("attendance", {
        "session_id": session["id"],
        "athlete_id": athlete["id"],
        "minutes_present": minutes_present,
        "required_minutes": required_minutes,
        "status": "COUNTED" if counted else "NOT_COUNTED",
        "counted_minutes": minutes_present if counted else 0,
        "season_id": session["season_id"],
    })
    live = len([r for r in db.attendance.values()
                if r["session_id"] == session["id"]
                and r["status"] in ("COUNTED", "NOT_COUNTED")])
    session["recorded_attendance_count"] = live
    if session["status"] == "SCHEDULED":
        session["status"] = "HELD"
    db.touch(session)
    derive.recompute_athlete_ledger(athlete)
    derive.recompute_program(program)
    return ok(ser_attendance(record), 201)

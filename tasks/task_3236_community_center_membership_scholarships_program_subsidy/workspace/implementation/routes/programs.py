"""Routes: programs, sessions, registrations."""
from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    ApiError, auth, require_role, require_member_owner, success_object, paginate,
    get_body, require_fields, today, parse_date, parse_time_hhmm, now_dt,
)
from services import (
    refresh_session_counts, effective_capacity, classify_registrant,
    compute_registration_fee, promote_waitlist, age_on,
)

bp = Blueprint("programs", __name__)

PROGRAM_FIELDS = [
    "id", "branch_id", "name", "kind", "member_only", "member_priority_days",
    "min_age", "max_age", "base_fee_cents", "non_member_multiplier",
    "is_licensed_childcare", "licensed_children_per_staff",
    "created_at", "updated_at", "version",
]
SESSION_FIELDS = [
    "id", "program_id", "branch_id", "space_id", "start_on", "end_on",
    "time_start", "time_end", "capacity", "enrolled_count", "waitlist_count",
    "staff_member_ids", "public_opens_on", "member_opens_on", "status",
    "created_at", "updated_at", "version",
]
REGISTRATION_FIELDS = [
    "id", "session_id", "member_id", "participant_name", "participant_birth_date",
    "registrant_class", "fee_charged_cents", "waitlist_position", "status",
    "created_at", "updated_at", "version",
]

PROGRAM_KINDS = {"SWIM_LESSON", "CHILDCARE", "CAMP", "SPORTS"}
READ_ROLES_PROGRAM = ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                      "FrontDesk", "Member", "BoardMember"]


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.route("/programs", methods=["POST"])
def create_program():
    role, _ = auth()
    require_role(role, ["ProgramCoordinator", "BranchDirector", "AssociationAdmin"])
    body = get_body()
    require_fields(body, ["branch_id", "name", "kind", "base_fee_cents"])
    if body["branch_id"] not in db.STORES["branches"]:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['branch_id']} not found")
    if body["kind"] not in PROGRAM_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid program kind")
    is_licensed = body.get("is_licensed_childcare", False)
    ratio = body.get("licensed_children_per_staff")
    if is_licensed and ratio is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "licensed_children_per_staff required for licensed childcare")
    rec = db.new_record("programs", {
        "branch_id": body["branch_id"],
        "name": body["name"],
        "kind": body["kind"],
        "member_only": body.get("member_only", False),
        "member_priority_days": body.get("member_priority_days", 0),
        "min_age": body.get("min_age", 0),
        "max_age": body.get("max_age", 99),
        "base_fee_cents": body["base_fee_cents"],
        "non_member_multiplier": body.get("non_member_multiplier", 1.5),
        "is_licensed_childcare": is_licensed,
        "licensed_children_per_staff": ratio,
    })
    return success_object(db.serialize(rec, PROGRAM_FIELDS), 201)


@bp.route("/programs/<programId>", methods=["GET"])
def get_program(programId):
    role, _ = auth()
    require_role(role, READ_ROLES_PROGRAM)
    rec = db.get("programs", programId)
    return success_object(db.serialize(rec, PROGRAM_FIELDS))


@bp.route("/programs", methods=["GET"])
def list_programs():
    role, _ = auth()
    require_role(role, READ_ROLES_PROGRAM)
    items = db.all_records("programs")
    branch_id = request.args.get("branch_id")
    kind = request.args.get("kind")
    if branch_id:
        items = [p for p in items if p["branch_id"] == branch_id]
    if kind:
        items = [p for p in items if p["kind"] == kind]
    return paginate([db.serialize(p, PROGRAM_FIELDS) for p in items])


@bp.route("/programs/<programId>/sessions", methods=["GET"])
def list_program_sessions(programId):
    role, _ = auth()
    require_role(role, READ_ROLES_PROGRAM)
    db.get("programs", programId)
    items = [s for s in db.all_records("sessions") if s["program_id"] == programId]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return paginate([db.serialize(s, SESSION_FIELDS) for s in items])


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@bp.route("/sessions", methods=["POST"])
def create_session():
    role, _ = auth()
    require_role(role, ["ProgramCoordinator", "BranchDirector"])
    body = get_body()
    require_fields(body, ["program_id", "space_id", "start_on", "end_on",
                          "time_start", "time_end", "capacity"])
    program = db.STORES["programs"].get(body["program_id"])
    if program is None:
        raise ApiError("ERR_NOT_FOUND", f"Program {body['program_id']} not found")
    space = db.STORES["spaces"].get(body["space_id"])
    if space is None or space["branch_id"] != program["branch_id"]:
        raise ApiError("ERR_SPACE_NOT_FOUND", "Space not found for this branch")
    start_on = parse_date(body["start_on"])
    end_on = parse_date(body["end_on"])
    time_start = parse_time_hhmm(body["time_start"])
    time_end = parse_time_hhmm(body["time_end"])
    if start_on is None or end_on is None or time_start is None or time_end is None:
        raise ApiError("ERR_TIME_RANGE_INVALID", "Invalid date or time format")
    if end_on < start_on or time_end <= time_start:
        raise ApiError("ERR_TIME_RANGE_INVALID", "end must be after start")
    public_opens = start_on - timedelta(days=14)
    member_opens = public_opens - timedelta(days=program.get("member_priority_days", 0))
    rec = db.new_record("sessions", {
        "program_id": program["id"],
        "branch_id": program["branch_id"],
        "space_id": space["id"],
        "start_on": start_on.isoformat(),
        "end_on": end_on.isoformat(),
        "time_start": body["time_start"],
        "time_end": body["time_end"],
        "capacity": body["capacity"],
        "enrolled_count": 0,
        "waitlist_count": 0,
        "staff_member_ids": list(body.get("staff_member_ids") or []),
        "public_opens_on": public_opens.isoformat(),
        "member_opens_on": member_opens.isoformat(),
        "status": "SCHEDULED",
    })
    return success_object(db.serialize(rec, SESSION_FIELDS), 201)


@bp.route("/sessions/<sessionId>", methods=["GET"])
def get_session(sessionId):
    role, _ = auth()
    require_role(role, READ_ROLES_PROGRAM)
    rec = db.get("sessions", sessionId)
    refresh_session_counts(rec)
    return success_object(db.serialize(rec, SESSION_FIELDS))


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    role, _ = auth()
    require_role(role, READ_ROLES_PROGRAM)
    items = db.all_records("sessions")
    program_id = request.args.get("program_id")
    branch_id = request.args.get("branch_id")
    space_id = request.args.get("space_id")
    status = request.args.get("status")
    if program_id:
        items = [s for s in items if s["program_id"] == program_id]
    if branch_id:
        items = [s for s in items if s["branch_id"] == branch_id]
    if space_id:
        items = [s for s in items if s["space_id"] == space_id]
    if status:
        items = [s for s in items if s["status"] == status]
    for s in items:
        refresh_session_counts(s)
    return paginate([db.serialize(s, SESSION_FIELDS) for s in items])


@bp.route("/sessions/<sessionId>/close-registration", methods=["POST"])
def close_registration(sessionId):
    role, _ = auth()
    require_role(role, ["ProgramCoordinator", "BranchDirector"])
    rec = db.get("sessions", sessionId)
    if rec["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Session is terminal")
    if rec["status"] != "REG_OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only REG_OPEN sessions can close registration")
    rec["status"] = "REG_CLOSED"
    db.touch(rec, bump=False)
    for reg in db.STORES["registrations"].values():
        if reg["session_id"] == rec["id"] and reg["status"] == "WAITLISTED":
            reg["status"] = "EXPIRED"
            reg["waitlist_position"] = None
            db.touch(reg, bump=False)
    refresh_session_counts(rec)
    return success_object(db.serialize(rec, SESSION_FIELDS))


@bp.route("/sessions/<sessionId>/cancel", methods=["POST"])
def cancel_session(sessionId):
    role, _ = auth()
    require_role(role, ["ProgramCoordinator", "BranchDirector"])
    rec = db.get("sessions", sessionId)
    if rec["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Session is terminal")
    if rec["status"] not in ("SCHEDULED", "REG_OPEN"):
        raise ApiError("ERR_INVALID_STATE", "Session cannot be cancelled from this state")
    rec["status"] = "CANCELLED"
    db.touch(rec, bump=False)
    for reg in db.STORES["registrations"].values():
        if reg["session_id"] != rec["id"]:
            continue
        if reg["status"] == "REGISTERED":
            reg["status"] = "REFUNDED"
            db.touch(reg, bump=False)
        elif reg["status"] == "WAITLISTED":
            reg["status"] = "EXPIRED"
            reg["waitlist_position"] = None
            db.touch(reg, bump=False)
    for res in db.STORES["reservations"].values():
        if (res.get("session_id") == rec["id"] and res["reservation_type"] == "PROGRAM"
                and res["status"] in ("REQUESTED", "APPROVED")):
            res["status"] = "CANCELLED"
            db.touch(res, bump=False)
    refresh_session_counts(rec)
    return success_object(db.serialize(rec, SESSION_FIELDS))


@bp.route("/sessions/<sessionId>/staff", methods=["POST"])
def assign_staff(sessionId):
    role, _ = auth()
    require_role(role, ["ProgramCoordinator", "BranchDirector"])
    rec = db.get("sessions", sessionId)
    if rec["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Session is terminal")
    body = get_body()
    require_fields(body, ["staff_member_ids"])
    staff = list(body["staff_member_ids"])
    program = db.STORES["programs"].get(rec["program_id"])
    refresh_session_counts(rec)
    if program is not None and program.get("is_licensed_childcare"):
        ratio = program.get("licensed_children_per_staff") or 0
        if rec["enrolled_count"] > ratio * len(staff):
            raise ApiError("ERR_RATIO_CAPACITY_EXCEEDED",
                           "Staff removal would break the licensing ratio")
    rec["staff_member_ids"] = staff
    db.touch(rec, bump=False)
    promote_waitlist(rec)
    return success_object(db.serialize(rec, SESSION_FIELDS))


@bp.route("/sessions/<sessionId>/registrations", methods=["GET"])
def list_session_registrations(sessionId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                        "FrontDesk", "Member"])
    db.get("sessions", sessionId)
    items = [r for r in db.all_records("registrations") if r["session_id"] == sessionId]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([db.serialize(r, REGISTRATION_FIELDS) for r in items])


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

@bp.route("/registrations", methods=["POST"])
def create_registration():
    role, user_id = auth()
    require_role(role, ["Member", "FrontDesk", "ProgramCoordinator"])
    body = get_body()
    require_fields(body, ["session_id", "member_id", "participant_name",
                          "participant_birth_date"])
    session = db.STORES["sessions"].get(body["session_id"])
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", f"Session {body['session_id']} not found")
    member = db.STORES["members"].get(body["member_id"])
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", f"Member {body['member_id']} not found")
    require_member_owner(role, user_id, member["id"])
    if session["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Session is terminal")
    if session["status"] == "REG_CLOSED":
        raise ApiError("ERR_REGISTRATION_WINDOW_CLOSED",
                       "Session registration window has closed")
    if session["status"] != "REG_OPEN":
        raise ApiError("ERR_REGISTRATION_WINDOW_CLOSED",
                       "Session registration window is not open")
    program = db.STORES["programs"].get(session["program_id"])
    branch = db.STORES["branches"].get(session["branch_id"])
    klass, home_membership = classify_registrant(member, session, branch)
    current = today()
    public_opens = parse_date(session["public_opens_on"])
    member_only = program.get("member_only", False)
    if member_only and klass in ("NON_MEMBER", "RECIPROCITY_VISITOR"):
        raise ApiError("ERR_MEMBER_ONLY_PROGRAM",
                       "Program is restricted to association members")
    if public_opens is not None and current < public_opens:
        # member-priority window (or before it entirely)
        if klass != "HOME_MEMBER":
            raise ApiError("ERR_MEMBER_PRIORITY_ONLY",
                           "Only home-branch members during the priority window")
    start_on = parse_date(session["start_on"])
    age = age_on(body["participant_birth_date"], start_on)
    if age < program.get("min_age", 0) or age > program.get("max_age", 99):
        raise ApiError("ERR_PARTICIPANT_AGE_INVALID",
                       "Participant age outside program bounds")
    refresh_session_counts(session)
    cap = effective_capacity(session)
    if session["enrolled_count"] + 1 <= cap:
        status = "REGISTERED"
        waitlist_position = None
        fee = compute_registration_fee(klass, home_membership, program)
        session["enrolled_count"] += 1
    else:
        status = "WAITLISTED"
        waitlist_position = session["waitlist_count"] + 1
        fee = None
        session["waitlist_count"] += 1
    rec = db.new_record("registrations", {
        "session_id": session["id"],
        "member_id": member["id"],
        "participant_name": body["participant_name"],
        "participant_birth_date": body["participant_birth_date"],
        "registrant_class": klass,
        "fee_charged_cents": fee,
        "waitlist_position": waitlist_position,
        "status": status,
    })
    return success_object(db.serialize(rec, REGISTRATION_FIELDS), 201)


@bp.route("/registrations/<registrationId>", methods=["GET"])
def get_registration(registrationId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                        "FrontDesk", "Member"])
    rec = db.get("registrations", registrationId)
    return success_object(db.serialize(rec, REGISTRATION_FIELDS))


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                        "FrontDesk", "Member"])
    items = db.all_records("registrations")
    session_id = request.args.get("session_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if session_id:
        items = [r for r in items if r["session_id"] == session_id]
    if member_id:
        items = [r for r in items if r["member_id"] == member_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([db.serialize(r, REGISTRATION_FIELDS) for r in items])


@bp.route("/registrations/<registrationId>/cancel", methods=["POST"])
def cancel_registration(registrationId):
    role, user_id = auth()
    require_role(role, ["Member", "ProgramCoordinator", "FrontDesk"])
    rec = db.get("registrations", registrationId)
    require_member_owner(role, user_id, rec["member_id"])
    session = db.STORES["sessions"].get(rec["session_id"])
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Session not found")
    if rec["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", "Only REGISTERED registrations can be cancelled")
    if session["status"] not in ("SCHEDULED", "REG_OPEN"):
        raise ApiError("ERR_INVALID_STATE",
                       "Registrations cannot be cancelled in this session state")
    rec["status"] = "CANCELLED"
    db.touch(rec, bump=False)
    refresh_session_counts(session)
    promote_waitlist(session)
    return success_object(db.serialize(rec, REGISTRATION_FIELDS))

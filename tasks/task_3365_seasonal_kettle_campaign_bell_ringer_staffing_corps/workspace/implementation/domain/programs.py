"""Corps community programs and their enrollment economy (PRD 3.7)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

CATEGORIES = ("YOUTH", "SENIOR", "WORSHIP", "COMMUNITY")
PROGRAM_STATUSES = ("PLANNED", "ACTIVE", "SUSPENDED", "COMPLETED")


def refresh_counts(program):
    enrolled, waitlisted = calcs.enrollment_counts(program)
    program["enrolled_count"] = enrolled
    program["waitlist_count"] = waitlisted
    store.touch(program)
    return program


@bp.route("/corps-programs", methods=["POST"])
def create_corps_program():
    require_role(["ProgramDirector", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("unit_id", validate.STRING, required=True),
            validate.f("name", validate.STRING, required=True),
            validate.f("category", validate.ENUM, required=True, enum=CATEGORIES),
            validate.f("capacity", validate.INTEGER, required=True),
            validate.f("waitlist_enabled", validate.BOOLEAN),
            validate.f("meeting_pattern", validate.STRING, required=True),
        ]
    )
    validate.reference("units", values["unit_id"], "unit")
    program = {
        "unit_id": values["unit_id"],
        "name": values["name"],
        "category": values["category"],
        "capacity": int(values["capacity"]),
        "waitlist_enabled": bool(values.get("waitlist_enabled", True)),
        "status": "PLANNED",
        "enrolled_count": 0,
        "waitlist_count": 0,
        "meeting_pattern": values["meeting_pattern"],
        "enrollment_log": [],
    }
    store.insert("corps_programs", program)
    return success(store.public(program)), 201


@bp.route("/corps-programs", methods=["GET"])
def list_corps_programs():
    require_role(
        [
            "PlatformAdmin",
            "ProgramDirector",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "VolunteerCoordinator",
        ]
    )
    args = request.args
    rows = store.ordered("corps_programs")
    for field in ("unit_id", "category", "status"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/corps-programs/<program_id>", methods=["GET"])
def get_corps_program(program_id):
    require_role(
        [
            "PlatformAdmin",
            "ProgramDirector",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "VolunteerCoordinator",
        ]
    )
    program = validate.path_row("corps_programs", program_id, "corps program")
    return success(store.public(program))


@bp.route("/corps-programs/<program_id>/activate", methods=["POST"])
def activate_corps_program(program_id):
    require_role(["ProgramDirector", "CorpsOfficer", "PlatformAdmin"])
    program = validate.path_row("corps_programs", program_id, "corps program")
    status = program.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "PLANNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if int(program.get("capacity", 0) or 0) < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "A program must hold at least one seat.")
    program["status"] = "ACTIVE"
    store.touch(program)
    return success(store.public(program))


@bp.route("/corps-programs/<program_id>/suspend", methods=["POST"])
def suspend_corps_program(program_id):
    require_role(["ProgramDirector", "CorpsOfficer", "PlatformAdmin"])
    program = validate.path_row("corps_programs", program_id, "corps program")
    status = program.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    program["status"] = "SUSPENDED"
    store.touch(program)
    return success(store.public(program))


@bp.route("/corps-programs/<program_id>/resume", methods=["POST"])
def resume_corps_program(program_id):
    require_role(["ProgramDirector", "CorpsOfficer", "PlatformAdmin"])
    program = validate.path_row("corps_programs", program_id, "corps program")
    if program.get("status") == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if program.get("status") != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    program["status"] = "ACTIVE"
    store.touch(program)
    return success(store.public(program))


@bp.route("/corps-programs/<program_id>/complete", methods=["POST"])
def complete_corps_program(program_id):
    require_role(["ProgramDirector", "PlatformAdmin"])
    program = validate.path_row("corps_programs", program_id, "corps program")
    status = program.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    enrolled, waitlisted = calcs.enrollment_counts(program)
    if waitlisted != 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The program still has a waitlist.")
    program["status"] = "COMPLETED"
    store.touch(program)
    return success(store.public(program))


@bp.route("/corps-programs/<program_id>/enroll", methods=["POST"])
def enroll_participant(program_id):
    require_role(["ProgramDirector", "CorpsOfficer", "VolunteerCoordinator", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("participant_name", validate.STRING, required=True),
            validate.f("participant_type", validate.STRING, required=True),
        ]
    )
    program = validate.path_row("corps_programs", program_id, "corps program")
    status = program.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("PLANNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    capacity = int(program.get("capacity", 0) or 0)
    if status == "PLANNED" and capacity < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "A program must hold at least one seat.")

    enrolled, _waitlisted = calcs.enrollment_counts(program)
    if enrolled >= capacity and not program.get("waitlist_enabled", True):
        raise ApiError("ERR_PROGRAM_AT_CAPACITY")

    log = program.setdefault("enrollment_log", [])
    log.append(
        {
            "participant_name": values["participant_name"],
            "participant_type": values["participant_type"],
            "enrolled_at": clock.now_iso(),
            "state": "ENROLLED",
        }
    )
    if status == "PLANNED":
        program["status"] = "ACTIVE"
    refresh_counts(program)
    return success(store.public(program))


@bp.route("/corps-programs/<program_id>/withdraw", methods=["POST"])
def withdraw_participant(program_id):
    require_role(["ProgramDirector", "CorpsOfficer", "VolunteerCoordinator", "PlatformAdmin"])
    values = validate.shape([validate.f("participant_name", validate.STRING, required=True)])
    program = validate.path_row("corps_programs", program_id, "corps program")
    if program.get("status") == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")

    log = calcs.enrollment_order(program.get("enrollment_log") or [])
    target = None
    for entry in log:
        if entry.get("participant_name") == values["participant_name"]:
            target = entry
            break
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "That participant is not enrolled in this program.")

    program["enrollment_log"] = [e for e in (program.get("enrollment_log") or []) if e is not target]
    refresh_counts(program)
    return success(store.public(program))

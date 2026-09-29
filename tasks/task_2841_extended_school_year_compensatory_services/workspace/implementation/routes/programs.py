"""ESY programs, their calendars and the day-cancellation cascade (PRD 3.3 / 3.6)."""
from flask import Blueprint

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PROGRAM_COORDINATOR,
                  SPED_DIRECTOR, endpoint)
from calcs import (derive_program_calendar, instructional_dates,
                   program_allocations_in_priority_order)
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from ledgers import (leave_assignment, recompute_commitment_ledger,
                     recompute_run_seats, recompute_student_ledger)
from resolve import path_ref
from serialize import allocations_public, many, public
from store import creation_order, db, new_record, touch
from validate import (WEEKDAY_NAMES, bad, body, parse_date_str, req_date,
                      req_enum, req_int, req_school_year, req_str)

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("PLANNING", "STAFFING_LOCKED", "OPEN", "CLOSED")
MISS_REASON_CODES = ("WEATHER", "STAFF_ABSENCE", "TRANSPORT_FAILURE",
                     "PARENT_CANCELLED", "STUDENT_ILL", "OTHER")
STAFF_READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR,
                    COMPLIANCE_OFFICER)
FUND_READ_ROLES = (PROGRAM_COORDINATOR, SPED_DIRECTOR, COMPLIANCE_OFFICER)


@bp.post("/esy/programs")
@endpoint((PROGRAM_COORDINATOR,))
def create_program():
    data = body()
    name = req_str(data, "name", 1, 80)
    school_year = req_school_year(data, "school_year")
    start_raw = req_date(data, "session_start_date")
    end_raw = req_date(data, "session_end_date")
    start = parse_date_str(start_raw, "session_start_date")
    end = parse_date_str(end_raw, "session_end_date")
    if end < start:
        raise bad("session_end_date must not be earlier than session_start_date.")

    weekdays = data.get("instructional_weekdays")
    if weekdays is None:
        raise bad("instructional_weekdays is required.")
    if not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 5:
        raise bad("instructional_weekdays must hold 1 to 5 entries.")
    for entry in weekdays:
        if not isinstance(entry, str) or entry not in WEEKDAY_NAMES:
            raise bad("instructional_weekdays entries must be MON..FRI.")
    if len(set(weekdays)) != len(weekdays):
        raise bad("instructional_weekdays entries must be distinct.")

    blackout = data.get("blackout_dates")
    if blackout is None:
        blackout = []
    if not isinstance(blackout, list):
        raise bad("blackout_dates must be an array.")
    for entry in blackout:
        day = parse_date_str(entry, "blackout_dates")
        if day < start or day > end:
            raise bad("blackout_dates entries must fall inside the session window.")

    daily_minutes_cap = req_int(data, "daily_minutes_cap", 1, 480)

    program = new_record("EsyProgram", {
        "name": name,
        "school_year": school_year,
        "session_start_date": start_raw,
        "session_end_date": end_raw,
        "instructional_weekdays": list(weekdays),
        "blackout_dates": list(blackout),
        "cancelled_dates": [],
        "daily_minutes_cap": daily_minutes_cap,
        "instructional_days_count": 0,
        "instructional_week_count": 0,
        "status": "PLANNING",
    })
    derive_program_calendar(program)
    db.programs[program["id"]] = program
    return created(public(program))


@bp.get("/esy/programs/<program_id>")
@endpoint(STAFF_READ_ROLES)
def get_program(program_id):
    return ok(public(path_ref("program", program_id)))


@bp.get("/esy/programs/<program_id>/fund-allocations")
@endpoint(FUND_READ_ROLES)
def list_program_fund_allocations(program_id):
    path_ref("program", program_id)
    rows = program_allocations_in_priority_order(program_id)
    page, page_meta = paginate(rows)
    return ok_list(allocations_public(page), page_meta)


@bp.get("/esy/programs/<program_id>/transportation-runs")
@endpoint(STAFF_READ_ROLES)
def list_program_transportation_runs(program_id):
    path_ref("program", program_id)
    rows = sorted(
        [r for r in db.runs.values() if r["program_id"] == program_id],
        key=lambda r: (r["service_date"], r["window_start_time"], r["created_at"],
                       r["_seq"]))
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)


def _program_commitments(program_id):
    return creation_order([c for c in db.commitments.values()
                           if c["program_id"] == program_id])


def _close_from_open(program):
    """PRD 3.3: the conditional split is the whole point of this cascade."""
    touched_runs = []
    for commitment in _program_commitments(program["id"]):
        if commitment["status"] in ("ACTIVE", "SUSPENDED"):
            target = "COMPLETED"
        elif commitment["status"] in ("PLANNED", "ASSIGNED"):
            target = "TERMINATED"
        else:
            continue
        for assignment in creation_order(
                [a for a in db.assignments.values()
                 if a["commitment_id"] == commitment["id"] and a["status"] == "ACTIVE"]):
            leave_assignment(assignment, "RELEASED", "PROGRAM_CLOSED")
        commitment["status"] = target
        touch(commitment)
        run_id = commitment.get("transportation_run_id")
        if run_id and run_id not in touched_runs:
            touched_runs.append(run_id)
    for run_id in touched_runs:
        run = db.runs.get(run_id)
        if run is not None:
            recompute_run_seats(run)


@bp.post("/esy/programs/<program_id>/status")
@endpoint((PROGRAM_COORDINATOR,))
def set_program_status(program_id):
    program = path_ref("program", program_id)
    data = body()
    target = req_enum(data, "target_status", PROGRAM_STATUSES)
    current = program["status"]

    if target == "STAFFING_LOCKED":
        if current != "PLANNING":
            raise ApiError("ERR_INVALID_STATE")
        if not any(c["status"] == "ASSIGNED" for c in _program_commitments(program_id)):
            raise ApiError("ERR_INVALID_STATE")
        program["status"] = "STAFFING_LOCKED"
    elif target == "OPEN":
        if current != "STAFFING_LOCKED":
            raise ApiError("ERR_INVALID_STATE")
        if any(c["status"] == "PLANNED" for c in _program_commitments(program_id)):
            raise ApiError("ERR_INVALID_STATE")
        program["status"] = "OPEN"
    elif target == "CLOSED":
        if current == "OPEN":
            _close_from_open(program)
        elif current == "PLANNING":
            for commitment in _program_commitments(program_id):
                commitment["status"] = "TERMINATED"
                touch(commitment)
        else:
            raise ApiError("ERR_INVALID_STATE")
        program["status"] = "CLOSED"
    else:
        raise ApiError("ERR_INVALID_STATE")

    touch(program)
    return ok(public(program))


@bp.post("/esy/programs/<program_id>/cancel-day")
@endpoint((PROGRAM_COORDINATOR,))
def cancel_program_day(program_id):
    program = path_ref("program", program_id)
    data = body()
    service_date = req_date(data, "service_date")
    reason = req_enum(data, "cancellation_reason", MISS_REASON_CODES)

    if program["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if not any(day.isoformat() == service_date
               for day in instructional_dates(program)):
        raise ApiError("ERR_NOT_INSTRUCTIONAL_DATE")

    program["cancelled_dates"].append(service_date)
    derive_program_calendar(program)
    touch(program)

    # CASCADE: only commitments sitting in exactly ACTIVE accrue a missed day.
    for commitment in _program_commitments(program_id):
        if commitment["status"] != "ACTIVE":
            continue
        log = new_record("ServiceLog", {
            "commitment_id": commitment["id"],
            "provider_id": None,
            "service_date": service_date,
            "outcome": "MISSED_DISTRICT",
            "minutes_scheduled": commitment["daily_minutes"],
            "minutes_delivered": 0,
            "miss_reason_code": reason,
            "status": "VERIFIED",
            "generated_by": "SYSTEM_DAY_CANCELLATION",
            "void_reason": None,
        })
        db.logs[log["id"]] = log
        recompute_commitment_ledger(commitment)
        student = db.students.get(commitment["student_id"])
        if student is not None:
            recompute_student_ledger(student)

    # FAN-OUT, outside the cascade chain: the day's scheduled runs are cancelled.
    for run in creation_order([r for r in db.runs.values()
                               if r["program_id"] == program_id
                               and r["service_date"] == service_date
                               and r["status"] == "SCHEDULED"]):
        run["status"] = "CANCELLED"
        touch(run)

    return ok(public(program))

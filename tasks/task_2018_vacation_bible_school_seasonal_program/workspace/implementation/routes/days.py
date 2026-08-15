"""Program days: calendar build, daily open/close gates (PRD §3.1, §3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from derived import (
    program_day_view,
    days_of_program,
    classrooms_of_program,
    enrolled_count,
    staffing_status,
    records_of_day,
)
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STAFFING_INADEQUATE,
    ERR_CHILDREN_ON_SITE,
    ERR_DAY_NOT_TODAY,
    ERR_DAY_OUT_OF_RANGE,
    ERR_DAY_NOT_SEQUENTIAL,
)
from routes.common import paginate, empty_body
from validate import Field, get_body, validate_body

bp = Blueprint("days", __name__)

_CREATE_SPEC = {
    "program_id": Field("str", required=True),
    "date": Field("date", required=True),
}

_READ_ROLES = ("ProgramDirector", "RegistrationCoordinator", "VolunteerCoordinator",
               "SafetyOfficer", "CheckInStaff")


def get_day_or_404(day_id):
    day = store.get("program_days", day_id)
    if day is None:
        raise_err(ERR_NOT_FOUND, "program day not found")
    return day


@bp.post("/vbs/days")
def create_day():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    program = store.get("programs", data["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    if program["status"] not in ("DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED"):
        raise_err(ERR_INVALID_STATE, "days may be appended only while DRAFT, REGISTRATION_OPEN or REGISTRATION_CLOSED")
    # P7(v) outranks P7(vi): range first, then adjacency.
    if not (program["start_date"] <= data["date"] <= program["end_date"]):
        raise_err(ERR_DAY_OUT_OF_RANGE, "day lies outside the program's inclusive range")
    existing = sorted(days_of_program(program["id"]), key=lambda d: d["day_index"])
    if not existing:
        if data["date"] != program["start_date"]:
            raise_err(ERR_DAY_NOT_SEQUENTIAL, "the first day must be the program start_date")
    else:
        if data["date"] != existing[-1]["date"] + timedelta(days=1):
            raise_err(ERR_DAY_NOT_SEQUENTIAL, "day must be exactly the previous day + 1")
    day = store.new_record(
        program_id=program["id"],
        day_index=len(existing) + 1,
        date=data["date"],
        status="SCHEDULED",
    )
    store.put("program_days", day)
    return ok_object(program_day_view(day), status=201)


@bp.post("/vbs/days/<day_id>/open")
def open_day(day_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    day = get_day_or_404(day_id)
    program = store.get("programs", day["program_id"])
    # P5 safety gate outranks the state and temporal gates.
    for classroom in classrooms_of_program(day["program_id"]):
        if enrolled_count(classroom) > 0 and staffing_status(classroom) != "ADEQUATE":
            raise_err(ERR_STAFFING_INADEQUATE, "an enrolled classroom lacks adequate staffing")
    if day["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "only a SCHEDULED day may be opened")
    if program is None or program["status"] != "IN_SESSION":
        raise_err(ERR_INVALID_STATE, "program is not IN_SESSION")
    if day["date"] != clock.today():
        raise_err(ERR_DAY_NOT_TODAY, "only today's program day may open")
    day["status"] = "OPEN"
    store.touch(day)
    if program is not None:
        program["current_day_index"] = day["day_index"]
        store.touch(program)
        classroom_ids = {c["id"] for c in classrooms_of_program(program["id"])}
        for reg in store.by_seq(
            r for r in store.all_of("registrations")
            if r["status"] == "ENROLLED" and r["classroom_id"] in classroom_ids
        ):
            exists = any(
                r["child_id"] == reg["child_id"] and r["program_day_id"] == day["id"]
                for r in store.all_of("attendance_records")
            )
            if not exists:
                store.put(
                    "attendance_records",
                    store.new_record(
                        child_id=reg["child_id"],
                        program_day_id=day["id"],
                        registration_id=reg["id"],
                        status="NOT_ARRIVED",
                        tag_code=None,
                        checked_in_at=None,
                        checked_out_at=None,
                        checked_in_by=None,
                        checked_out_by=None,
                        pickup_person=None,
                        late_pickup=False,
                    ),
                )
    return ok_object(program_day_view(day))


@bp.post("/vbs/days/<day_id>/close")
def close_day(day_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    day = get_day_or_404(day_id)
    program = store.get("programs", day["program_id"])
    # P5 safety gate ahead of the state gate.
    if any(r["status"] == "CHECKED_IN" for r in records_of_day(day["id"])):
        raise_err(ERR_CHILDREN_ON_SITE, "children remain checked in")
    if day["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "only an OPEN day may be closed")
    for rec in records_of_day(day["id"]):
        if rec["status"] == "NOT_ARRIVED":
            rec["status"] = "ABSENT"
            store.touch(rec)
    day["status"] = "CLOSED"
    store.touch(day)
    if program is not None:
        program["current_day_index"] = 0
        store.touch(program)
    return ok_object(program_day_view(day))


@bp.get("/vbs/days/<day_id>")
def get_day(day_id):
    ctx = authenticate()
    require_role(ctx, *_READ_ROLES)
    return ok_object(program_day_view(get_day_or_404(day_id)))


@bp.get("/vbs/days")
def list_days():
    ctx = authenticate()
    require_role(ctx, *_READ_ROLES)
    items = list(store.all_of("program_days"))
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [d for d in items if d["program_id"] == program_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate(items, program_day_view)

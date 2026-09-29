"""Transportation runs: closed-interval windows and the turnaround gap (PRD 3.3)."""
from flask import Blueprint

from auth import PROGRAM_COORDINATOR, endpoint
from calcs import ROUTE_TURNAROUND_MINUTES, instructional_dates
from envelope import created
from errors import ApiError
from resolve import body_ref
from serialize import public
from store import db, new_record
from validate import bad, body, minutes_of, req_date, req_int, req_str, req_time

bp = Blueprint("transportation", __name__)

RUN_HOST_PROGRAM_STATES = ("PLANNING", "STAFFING_LOCKED", "OPEN")


@bp.post("/esy/transportation-runs")
@endpoint((PROGRAM_COORDINATOR,))
def create_transportation_run():
    data = body()
    program = body_ref(data, "program_id", "program")
    program_id = req_str(data, "program_id", 1, None)
    route_code = req_str(data, "route_code", 1, 12)
    service_date = req_date(data, "service_date")
    window_start = req_time(data, "window_start_time")
    window_end = req_time(data, "window_end_time")
    if minutes_of(window_end) <= minutes_of(window_start):
        raise bad("window_end_time must be strictly later than window_start_time.")
    seats = req_int(data, "vehicle_capacity_seats", 1, 40)

    if program["status"] not in RUN_HOST_PROGRAM_STATES:
        raise ApiError("ERR_INVALID_STATE")

    new_start = minutes_of(window_start)
    new_end = minutes_of(window_end)
    siblings = [r for r in db.runs.values()
                if r["route_code"] == route_code
                and r["service_date"] == service_date
                and r["status"] == "SCHEDULED"]

    # PRD 3.3: the run window is a CLOSED interval, so touching endpoints collide.
    for run in siblings:
        other_start = minutes_of(run["window_start_time"])
        other_end = minutes_of(run["window_end_time"])
        if new_start <= other_end and other_start <= new_end:
            raise ApiError("ERR_RUN_WINDOW_OVERLAP")

    # PRD 3.3: non-overlapping runs of the same route must leave the turnaround gap.
    for run in siblings:
        other_start = minutes_of(run["window_start_time"])
        other_end = minutes_of(run["window_end_time"])
        if new_start > other_end:
            gap = new_start - other_end
        else:
            gap = other_start - new_end
        if 0 < gap < ROUTE_TURNAROUND_MINUTES:
            raise ApiError("ERR_ROUTE_TURNAROUND_VIOLATION")

    if not any(day.isoformat() == service_date for day in instructional_dates(program)):
        raise ApiError("ERR_NOT_INSTRUCTIONAL_DATE")

    run = new_record("TransportationRun", {
        "program_id": program_id,
        "route_code": route_code,
        "service_date": service_date,
        "window_start_time": window_start,
        "window_end_time": window_end,
        "vehicle_capacity_seats": seats,
        "seats_committed": 0,
        "status": "SCHEDULED",
    })
    db.runs[run["id"]] = run
    return created(public(run))

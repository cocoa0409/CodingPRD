"""ServiceSchedule endpoints: route attachment, listing and suspension."""
from flask import Blueprint

from auth import ALL_ROLES, endpoint
import constants as C
from db import db, insert, ordered, serialize
from errors import fail
from responses import created, ok
from routes.common import list_response, resolve
import services
import validation as V

bp = Blueprint("schedules", __name__)


@bp.post("/service-schedules")
@endpoint(["DispatchPlanner"])
def create_schedule():
    body = V.body()
    contract_id = V.str_field(body, "contract_id", 1)
    route_id = V.str_field(body, "route_id", 1)
    service_day = V.enum_field(body, "service_day", C.SERVICE_DAYS)
    window_start_minute = V.int_field(body, "window_start_minute", 0, 1439)
    window_end_minute = V.int_field(body, "window_end_minute", 1, 1440)
    V.ordering(window_start_minute, window_end_minute,
               "window_start_minute", "window_end_minute", strict=True)

    contract = resolve("rental_contracts", contract_id)
    route = resolve("routes", route_id)

    if service_day != route["service_day"]:
        V.bad("service_day must equal the route's own service_day.")

    units_on_route = sum(line["quantity"]
                         for line in services.active_quote_lines(contract["id"]))
    if route["committed_units"] + units_on_route > route["truck_capacity_units"]:
        fail("ERR_ROUTE_UNIT_CAPACITY_EXCEEDED")

    row = insert("service_schedules", {
        "contract_id": contract["id"],
        "route_id": route["id"],
        "service_day": service_day,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
        "units_on_route": units_on_route,
        "state": "ACTIVE",
    })
    services.recompute_route_planned(route)
    return created(serialize(row))


@bp.get("/service-schedules/<schedule_id>")
@endpoint(ALL_ROLES)
def read_schedule(schedule_id):
    return ok(serialize(resolve("service_schedules", schedule_id)))


@bp.get("/service-schedules")
@endpoint(ALL_ROLES)
def list_schedules():
    limit, offset = V.pagination()
    contract_id = V.q_str("contract_id")
    route_id = V.q_str("route_id")
    state = V.q_enum("state", C.SCHEDULE_STATES)
    rows = ordered(db.service_schedules.values())
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if route_id is not None:
        rows = [r for r in rows if r["route_id"] == route_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return list_response(rows, limit, offset)


@bp.post("/service-schedules/<schedule_id>/suspend")
@endpoint(["DispatchPlanner"])
def suspend_schedule(schedule_id):
    body = V.body()
    V.str_field(body, "suspension_reason", 1, None, required=False)
    schedule = resolve("service_schedules", schedule_id)

    if schedule["state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")

    services.suspend_schedule(schedule)
    return ok(serialize(schedule))

"""Production-entry endpoints."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, actor_id, endpoint
from errors import ApiError

bp = Blueprint("production", __name__)


def maybe_expire(permit):
    """ACTIVE -> EXPIRED when the logical clock date is past window_end."""
    if permit is None or permit.get("status") != "ACTIVE":
        return permit
    if store.today_str() > (permit.get("window_end") or ""):
        permit["status"] = "EXPIRED"
        store.touch(permit)
    return permit


@bp.post("/vm/production-entries")
@endpoint(["CrewForeman"])
def create_entry():
    data = V.body()

    # priority 3: crew ownership
    raw_assignment = data.get("crew_assignment_id")
    known = store.crew_assignments.get(raw_assignment) if isinstance(raw_assignment, str) \
        else None
    if known is not None and known.get("crew_id") != actor_id():
        raise ApiError("ERR_NOT_CREW_OWNER",
                       "the booking does not belong to the acting crew")

    assignment = V.body_fk(data, "crew_assignment_id", store.crew_assignments,
                           "ERR_CREW_ASSIGNMENT_NOT_FOUND")
    permit = V.body_fk(data, "herbicide_permit_id", store.herbicide_permits,
                       "ERR_PERMIT_NOT_FOUND")
    if assignment is None:
        V.require(data, "crew_assignment_id")

    work_date = V.as_date(data, "work_date")
    units = V.as_integer(data, "units_trimmed", minimum=0)
    labor_hours = V.as_number(data, "labor_hours", minimum=0, maximum=24)
    equipment_hours = V.as_number(data, "equipment_hours", minimum=0, maximum=24)
    disposal = V.as_number(data, "disposal_tons", required=False, minimum=0)
    disposal = 0 if disposal is None else disposal
    gallons = V.as_number(data, "gallons_applied", required=False, minimum=0)
    gallons = 0 if gallons is None else gallons
    if gallons > 0 and permit is None:
        V.bad("herbicide_permit_id is required when gallons_applied > 0")

    crew = services.crew_of_assignment(assignment)
    work_order = store.work_orders.get(assignment.get("work_order_id"))

    if gallons > 0:
        maybe_expire(permit)
        if permit.get("status") != "ACTIVE":
            raise ApiError("ERR_PERMIT_NOT_ACTIVE", "the named permit is not ACTIVE")
        if not (permit.get("window_start") <= work_date <= permit.get("window_end")):
            raise ApiError("ERR_APPLICATION_OUTSIDE_PERMIT_WINDOW",
                           "work_date is outside the permit's closed window")
        if float(permit.get("buffer_ft") or 0) > 0 and work_order is not None:
            blocked = [n for n in services.order_notifications(work_order["id"])
                       if n.get("status") == "FINAL_REFUSAL"]
            if blocked:
                raise ApiError("ERR_BUFFER_VIOLATION",
                               "a FINAL_REFUSAL premise sits inside the permit buffer")
        if crew is None or crew.get("crew_type") != "HERBICIDE":
            raise ApiError("ERR_CREW_TYPE_MISMATCH",
                           "only a HERBICIDE crew may report gallons")

    if work_order is not None:
        planned = Decimal(int(work_order.get("planned_unit_count") or 0))
        ceiling = int((planned * calc.UNIT_OVERRUN_TOLERANCE).to_integral_value(
            rounding="ROUND_FLOOR"))
        if int(work_order.get("actual_units_completed") or 0) + units > ceiling:
            raise ApiError("ERR_UNITS_EXCEED_PLANNED",
                           "units would exceed 110 percent of the planned count")

    rec = store.new_record(common=False)
    rec.update({
        "crew_assignment_id": assignment["id"],
        "herbicide_permit_id": permit["id"] if permit is not None else None,
        "work_date": work_date,
        "units_trimmed": units,
        "labor_hours": labor_hours,
        "equipment_hours": equipment_hours,
        "disposal_tons": disposal,
        "gallons_applied": gallons,
        "entry_cents": 0,
    })
    rec["entry_cents"] = calc.production_entry_cents(rec, crew) if crew else 0
    store.production_entries[rec["id"]] = rec

    if work_order is not None:
        work_order["actual_units_completed"] = (
            int(work_order.get("actual_units_completed") or 0) + units)
        store.touch(work_order)
        services.recompute_plan(services.plan_of_order(work_order))
    return envelope.created(store.public(rec))


@bp.get("/vm/production-entries/<eid>")
@endpoint(ALL_ROLES)
def get_entry(eid):
    rec = V.find(store.production_entries, eid, "ERR_PRODUCTION_ENTRY_NOT_FOUND")
    return envelope.ok(store.public(rec))


@bp.get("/vm/production-entries")
@endpoint(ALL_ROLES)
def list_entries():
    return envelope.list_response(list(store.production_entries.values()), {
        "crew_assignment_id": request.args.get("crew_assignment_id"),
        "herbicide_permit_id": request.args.get("herbicide_permit_id"),
        "work_date": request.args.get("work_date"),
    })

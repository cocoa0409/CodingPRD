"""Storm events: declaration, pool opening and closure."""
from flask import Blueprint

import calc
from common import (
    ApiError, DB, STATE_CODE_RE, authenticate, f_enum, f_int, f_str, get_body,
    must, new_row, ok, public, touch,
)

bp = Blueprint("storm", __name__, url_prefix="/distribution")

STORM_READERS = ["PlatformAdmin", "SalesRep", "WarehouseOperator", "ComplianceOfficer", "Customer"]


@bp.post("/storm-events")
def declare_storm():
    authenticate(["ComplianceOfficer", "PlatformAdmin"])
    body = get_body()
    name = f_str(body, "name")
    region = f_str(body, "region_state_code", pattern=STATE_CODE_RE)
    severity = f_enum(body, "severity_tier", ("WATCH", "WARNING", "EMERGENCY"))
    pool = f_int(body, "allocation_pool_units", minimum=1)
    row = new_row({
        "name": name,
        "region_state_code": region,
        "severity_tier": severity,
        "allocation_pool_units": pool,
        "allocated_units": 0,
        "remaining_pool_units": pool,
        "min_priority_score": calc.SEVERITY_MIN_SCORE[severity],
        "status": "DECLARED",
    })
    DB.storm_events[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/storm-events/<storm_event_id>")
def read_storm(storm_event_id):
    authenticate(STORM_READERS)
    return ok(public(must("storm_events", storm_event_id)))


@bp.post("/storm-events/<storm_event_id>/open-allocation")
def open_allocation(storm_event_id):
    authenticate(["ComplianceOfficer", "PlatformAdmin"])
    row = must("storm_events", storm_event_id)
    get_body()
    if row["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", "storm event is not DECLARED")
    row["status"] = "ALLOCATING"
    touch(row)
    return ok(public(row))


@bp.post("/storm-events/<storm_event_id>/close")
def close_storm(storm_event_id):
    authenticate(["ComplianceOfficer", "PlatformAdmin"])
    row = must("storm_events", storm_event_id)
    get_body()
    if row["status"] not in ("DECLARED", "ALLOCATING"):
        raise ApiError("ERR_INVALID_STATE", "storm event is already closed")
    row["status"] = "CLOSED"
    touch(row)
    return ok(public(row))

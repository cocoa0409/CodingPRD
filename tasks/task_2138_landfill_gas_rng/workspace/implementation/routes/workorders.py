"""WorkOrder and CondensateHaul endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import derived
import store
from auth import authenticate, require_role
from common import r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import haul_out, work_order_out
from validation import Field, parse_body, validate

bp = Blueprint("workorders", __name__)

ZERO = Decimal("0")
BUFFER = timedelta(minutes=calc.LOCKOUT_BUFFER_MINUTES)

WORK_ORDER_FIELDS = [
    Field("well_id", "string", required=True),
    Field(
        "work_type",
        "enum",
        required=True,
        values=("WELL_RETUNE", "LATERAL_REPAIR", "SUMP_PUMP_SERVICE", "HEADER_DEWATERING"),
    ),
    Field("window_start", "datetime", required=True),
    Field("window_end", "datetime", required=True),
]


def _hauls_of(work_order_id):
    return store.ordered(
        [h for h in store.condensate_hauls.values() if h["work_order_id"] == work_order_id]
    )


@bp.post("/work-orders")
def create_work_order():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician"])
    body = parse_body()
    data = validate(body, WORK_ORDER_FIELDS)

    well = must_find("well", data["well_id"])

    # Priority 57 - interval direction.
    if data["window_end"] <= data["window_start"]:
        fail("ERR_INTERVAL_INVALID", "window_end must be strictly after window_start.")

    # Priority 80 - a decommissioned well accepts no maintenance.
    if well["operating_state"] == "DECOMMISSIONED":
        fail("ERR_WELL_DECOMMISSIONED", "The well has been decommissioned.")

    # Priority 110 - buffered CLOSED-interval occupancy on the well.
    new_start = data["window_start"] - BUFFER
    new_end = data["window_end"] + BUFFER
    for incumbent in store.work_orders.values():
        if incumbent["well_id"] != well["id"]:
            continue
        if incumbent["status"] not in ("PLANNED", "IN_PROGRESS"):
            continue
        inc_buffer = timedelta(minutes=incumbent["lockout_buffer_minutes"])
        inc_start = incumbent["window_start"] - inc_buffer
        inc_end = incumbent["window_end"] + inc_buffer
        if new_start <= inc_end and inc_start <= new_end:
            fail(
                "ERR_WELL_LOCKOUT_CONFLICT",
                "The buffered lockout window collides with an existing job on this well.",
            )

    row = store.new_row(
        well_id=well["id"],
        work_type=data["work_type"],
        window_start=data["window_start"],
        window_end=data["window_end"],
        lockout_buffer_minutes=calc.LOCKOUT_BUFFER_MINUTES,
        status="PLANNED",
        actual_start_at=None,
        actual_end_at=None,
        condensate_gallons_removed=ZERO,
    )
    store.work_orders[row["id"]] = row
    return object_response(work_order_out(row), 201)


@bp.get("/work-orders/<work_order_id>")
def read_work_order(work_order_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician", "ComplianceOfficer"])
    row = must_find("work_order", work_order_id)
    return object_response(work_order_out(row))


@bp.get("/work-orders")
def list_work_orders():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician", "ComplianceOfficer"])
    limit, offset = pagination()
    rows = store.ordered(store.work_orders.values())
    rows = filter_equal(rows, "well_id", arg("well_id"))
    rows = filter_equal(rows, "status", arg("status"))
    return paginate(rows, limit, offset, work_order_out)


WORK_ORDER_STATUS_FIELDS = [
    Field(
        "to_status",
        "enum",
        required=True,
        values=("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"),
    ),
]

WORK_ORDER_TRANSITIONS = {
    ("PLANNED", "IN_PROGRESS"),
    ("IN_PROGRESS", "COMPLETED"),
    ("PLANNED", "CANCELLED"),
}


@bp.post("/work-orders/<work_order_id>/status")
def work_order_status(work_order_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician"])
    work_order = must_find("work_order", work_order_id)
    body = parse_body()
    data = validate(body, WORK_ORDER_STATUS_FIELDS)

    target = data["to_status"]
    current = work_order["status"]
    well = store.wells.get(work_order["well_id"])

    # Priority 80 - state legality.
    if (current, target) not in WORK_ORDER_TRANSITIONS:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    if target == "IN_PROGRESS":
        if well is None:
            fail("ERR_WELL_NOT_FOUND", "The well no longer exists.")
        if well["operating_state"] == "DECOMMISSIONED":
            fail("ERR_WELL_DECOMMISSIONED", "The well has been decommissioned.")
        if well["operating_state"] == "MAINTENANCE_LOCKOUT":
            fail("ERR_WELL_IN_LOCKOUT", "The well is already locked out by another job.")

        # Priority 110 - the logical clock must sit inside the planned window.
        current_utc = store.now()
        if current_utc < work_order["window_start"] or current_utc > work_order["window_end"]:
            fail(
                "ERR_WORK_ORDER_WINDOW_NOT_ACTIVE",
                "current_utc is outside the planned maintenance window.",
            )

        derived.apply_changes(
            work_order, {"status": "IN_PROGRESS", "actual_start_at": current_utc}
        )
        derived.apply_changes(
            well,
            {
                "operating_state": "MAINTENANCE_LOCKOUT",
                "lockout_work_order_id": work_order["id"],
                "current_flow_scfm": r2(ZERO),
            },
        )
        site = store.sites.get(well["site_id"])
        if site is not None:
            derived.recompute_site_flow(site)
            derived.propagate_shortfall(site)

    elif target == "COMPLETED":
        gallons = ZERO
        for haul in _hauls_of(work_order["id"]):
            gallons += haul["gallons"]
        derived.apply_changes(
            work_order,
            {
                "status": "COMPLETED",
                "actual_end_at": store.now(),
                "condensate_gallons_removed": gallons,
            },
        )
        if well is not None and well["operating_state"] == "MAINTENANCE_LOCKOUT":
            derived.apply_changes(
                well,
                {
                    "operating_state": "ISOLATED",
                    "lockout_work_order_id": None,
                    "consecutive_good_readings": 0,
                    "current_flow_scfm": r2(ZERO),
                },
            )
            site = store.sites.get(well["site_id"])
            if site is not None:
                derived.recompute_site_flow(site)

    else:  # CANCELLED
        derived.apply_changes(work_order, {"status": "CANCELLED"})

    return object_response(work_order_out(work_order))


HAUL_FIELDS = [
    Field("gallons", "number", required=True, gt=0),
    Field("disposal_manifest_no", "string", required=True, max_len=40),
    Field("hauled_at", "datetime", required=True),
    Field("is_hazardous", "boolean", default=False),
]


@bp.post("/work-orders/<work_order_id>/condensate-hauls")
def create_haul(work_order_id):
    caller = authenticate()
    require_role(caller, ["WellfieldTechnician"])
    work_order = must_find("work_order", work_order_id)
    body = parse_body()
    data = validate(body, HAUL_FIELDS)

    # Priority 80 - the job must be in progress.
    if work_order["status"] != "IN_PROGRESS":
        fail(
            "ERR_INVALID_TRANSITION",
            "Condensate may only be hauled against an IN_PROGRESS work order.",
        )

    # Priority 90 - hazardous waste manifest gate.
    if data["is_hazardous"] and not data["disposal_manifest_no"].startswith("HW-"):
        fail(
            "ERR_CONDENSATE_MANIFEST_REQUIRED",
            "Hazardous condensate requires a manifest number beginning with 'HW-'.",
        )

    haul = store.new_event_row(
        work_order_id=work_order["id"],
        gallons=data["gallons"],
        disposal_manifest_no=data["disposal_manifest_no"],
        hauled_at=data["hauled_at"],
        is_hazardous=data["is_hazardous"],
    )
    store.condensate_hauls[haul["id"]] = haul

    gallons = ZERO
    for row in _hauls_of(work_order["id"]):
        gallons += row["gallons"]
    derived.apply_changes(work_order, {"condensate_gallons_removed": gallons})

    return object_response(haul_out(haul), 201)


@bp.get("/work-orders/<work_order_id>/condensate-hauls")
def list_hauls(work_order_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician", "ComplianceOfficer"])
    work_order = must_find("work_order", work_order_id)
    limit, offset = pagination()
    rows = _hauls_of(work_order["id"])
    return paginate(rows, limit, offset, haul_out)

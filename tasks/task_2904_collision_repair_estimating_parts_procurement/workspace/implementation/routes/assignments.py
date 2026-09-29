"""Stall bookings and the stage successor map (PRD 3.8)."""
from flask import Blueprint, request

import auth
import calc
import db
import guards
import response
import serialize
import validate
from db import store
from errors import raise_error
from validate import F

bp = Blueprint("assignments", __name__)

ASSIGNMENT_STAGES = ("REPAIR", "REFINISH_CALIBRATION")
ASSIGNMENT_STATUSES = ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")
STALL_TYPE_FOR_STAGE = {
    "REPAIR": ("BODY", "FRAME"),
    "REFINISH_CALIBRATION": ("PAINT",),
}

SUCCESSOR = {
    "ESTIMATE_LOCKED": ("PARTS_STAGED",),
    "PARTS_STAGED": ("REPAIR",),
    "QC_FAILED": ("REPAIR",),
    "REPAIR": ("REFINISH_CALIBRATION",),
    "REFINISH_CALIBRATION": ("READY_FOR_QC",),
}

MINUTE = 60


def _find_assignment(assignment_id):
    """Rung 10, the stall-booking path identifier."""
    row = store.stage_assignments.get(assignment_id)
    if row is None:
        raise_error("ERR_STAGE_ASSIGNMENT_NOT_FOUND")
    return row


def _find_stall(stall_id):
    row = store.stalls.get(stall_id)
    if row is None:
        raise_error("ERR_STALL_NOT_FOUND")
    return row


BOOKING_SPEC = [
    F("stall_id", "string", required=True),
    F("stage", "string", required=True, enum=ASSIGNMENT_STAGES),
    F("window_start", "string", required=True),
    F("window_end", "string", required=True),
]


@bp.route("/repair-orders/<order_id>/stage-assignments", methods=["POST"])
def create_stage_assignment(order_id):
    auth.authenticate(("Technician",))
    data = validate.body(BOOKING_SPEC)
    start, end = validate.window(data)
    order = guards.find_order(order_id)
    stall = _find_stall(data["stall_id"])
    guards.not_terminal(order)

    if stall["stall_type"] not in STALL_TYPE_FOR_STAGE[data["stage"]]:
        raise_error("ERR_STALL_TYPE_MISMATCH")
    if stall.get("status") != "AVAILABLE":
        raise_error("ERR_STALL_UNAVAILABLE")

    buffer_seconds = int(stall.get("cleanup_buffer_minutes") or 0) * MINUTE
    for other in store.stage_assignments.values():
        if other.get("stall_id") != stall["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        other_start = db.parse_iso(other.get("window_start"))
        other_end = db.parse_iso(other.get("window_end"))
        if other_start is None or other_end is None:
            continue
        # the exclusion zone around an existing booking is closed on both sides
        low = other_start.timestamp() - buffer_seconds
        high = other_end.timestamp() + buffer_seconds
        if start.timestamp() <= high and end.timestamp() >= low:
            raise_error("ERR_STALL_WINDOW_CONFLICT")

    bumper = calc.Bumper()
    row = db.base_row()
    row.update({
        "repair_order_id": order["id"],
        "stall_id": stall["id"],
        "stage": data["stage"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "status": "SCHEDULED",
        "occupied_minutes": db.floor_minutes(start, end),
    })
    store.stage_assignments[row["id"]] = row
    calc.stall_rollup(stall)
    bumper.add(stall)
    bumper.flush()
    return response.created(serialize.stage_assignment(row))


@bp.route("/stage-assignments/<assignment_id>", methods=["GET"])
def read_stage_assignment(assignment_id):
    auth.authenticate(("ShopAdmin", "Technician"))
    return response.ok(serialize.stage_assignment(_find_assignment(assignment_id)))


@bp.route("/stage-assignments", methods=["GET"])
def list_stage_assignments():
    auth.authenticate(("ShopAdmin", "Technician"))
    status = validate.enum_filter(request.args, "status", ASSIGNMENT_STATUSES)
    limit, offset = response.read_pagination(request.args)
    stall_id = request.args.get("stall_id")
    if stall_id is not None:
        _find_stall(stall_id)
    order_id = request.args.get("repair_order_id")

    rows = db.in_creation_order(list(store.stage_assignments.values()))
    if order_id is not None:
        rows = [r for r in rows if r["repair_order_id"] == order_id]
    if stall_id is not None:
        rows = [r for r in rows if r["stall_id"] == stall_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows, limit, offset, serialize.stage_assignment)


@bp.route("/stage-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_stage_assignment(assignment_id):
    auth.authenticate(("Technician",))
    validate.body([])
    assignment = _find_assignment(assignment_id)
    order = store.repair_orders.get(assignment["repair_order_id"])
    guards.not_terminal(order)
    if assignment["status"] != "SCHEDULED":
        raise_error("ERR_ASSIGNMENT_NOT_SCHEDULED")

    bumper = calc.Bumper()
    assignment["status"] = "CANCELLED"
    stall = store.stalls.get(assignment["stall_id"])
    if stall is not None:
        calc.stall_rollup(stall)
        bumper.add(stall)
    bumper.add(assignment)
    bumper.flush()
    return response.ok(serialize.stage_assignment(assignment))


ADVANCE_SPEC = [F("to_stage", "string", required=True, enum=guards.STAGES)]


def _has_scheduled(order, stage):
    for assignment in calc.order_assignments(order["id"]):
        if assignment["status"] == "SCHEDULED" and assignment["stage"] == stage:
            return True
    return False


@bp.route("/repair-orders/<order_id>/stage-advance", methods=["POST"])
def advance_stage(order_id):
    auth.authenticate(("Technician",))
    data = validate.body(ADVANCE_SPEC)
    order = guards.find_order(order_id)
    guards.not_terminal(order)

    to_stage = data["to_stage"]
    if to_stage not in SUCCESSOR.get(order["stage"], ()):
        raise_error("ERR_STAGE_SEQUENCE_INVALID")
    guards.posture_open(order)

    records = calc.order_procedure_records(order["id"])
    parts_lines = calc.order_parts_lines(order["id"])

    # rung 14: safety and compliance, above every constraint
    if to_stage == "READY_FOR_QC":
        for record in records:
            if record["requires_calibration"] and record["calibration_status"] != "PASSED":
                raise_error("ERR_CALIBRATION_NOT_VERIFIED")
        for record in records:
            if not record["adherence_documented"]:
                raise_error("ERR_PROCEDURE_ADHERENCE_MISSING")
    elif to_stage == "REFINISH_CALIBRATION":
        for record in records:
            if record["operation_scope"] == "STRUCTURAL" \
                    and not record["adherence_documented"]:
                raise_error("ERR_PROCEDURE_ADHERENCE_MISSING")

    # rung 16: constraint satisfaction
    if to_stage == "PARTS_STAGED":
        for parts_line in parts_lines:
            if parts_line["procurement_status"] in ("PLANNED", "QUOTED", "COUNTERED",
                                                    "PRICE_LOCKED"):
                raise_error("ERR_PARTS_NOT_PROCURED")
    elif to_stage == "REFINISH_CALIBRATION":
        for parts_line in parts_lines:
            if parts_line["procurement_status"] in ("ORDERED", "RECEIVED"):
                raise_error("ERR_PARTS_NOT_INSTALLED")
    if to_stage in ("REPAIR", "REFINISH_CALIBRATION") and not _has_scheduled(order, to_stage):
        raise_error("ERR_NO_STAGE_ASSIGNMENT")

    bumper = calc.Bumper()
    order["stage"] = to_stage
    if to_stage == "REPAIR":
        guards.activate_assignments(order, "REPAIR", bumper)
    elif to_stage == "REFINISH_CALIBRATION":
        guards.release_assignments(order, ("ACTIVE",), "COMPLETED", bumper, stage="REPAIR")
        guards.activate_assignments(order, "REFINISH_CALIBRATION", bumper)
    elif to_stage == "READY_FOR_QC":
        guards.release_assignments(order, ("ACTIVE",), "COMPLETED", bumper)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.repair_order(order))

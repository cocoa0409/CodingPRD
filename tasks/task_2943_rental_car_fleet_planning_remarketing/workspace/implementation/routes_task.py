"""In-fleeting tasks: scheduling, bay collision, capacity and resolution (PRD 3.4)."""

import datetime

from flask import Blueprint

import calc
import cascade
import serialize
import validate
from auth import ALL_ROLES, authorize, require_scope
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, parse_instant, store, touch

bp = Blueprint("task", __name__)

TASK_TYPES = ("REGISTRATION", "LICENSING", "PREPARATION")
PREP_ACTIVE_STATUSES = ("PENDING", "COMPLETED")
BUFFER = datetime.timedelta(minutes=calc.PREP_BAY_BUFFER_MINUTES)


def _require_omitted(payload, field):
    if not validate.missing(payload, field):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be omitted unless task_type is PREPARATION." % field,
        )


@bp.route("/fleet/vehicles/<vehicle_id>/in-fleeting-tasks", methods=["POST"])
def schedule_task(vehicle_id):
    actor, _role = authorize(("MarketOperator",))
    vehicle = validate.load("vehicle", vehicle_id)
    require_scope(actor, vehicle["current_market_id"])
    payload = validate.body()

    task_type = validate.s_enum(payload, "task_type", TASK_TYPES)
    cost_cents = validate.s_int(payload, "cost_cents", ge=0)
    if task_type == "PREPARATION":
        bay_code = validate.s_str(payload, "bay_code")
        window_start, start_dt = validate.s_instant(payload, "window_start")
        window_end, end_dt = validate.s_instant(payload, "window_end")
    else:
        for field in ("bay_code", "window_start", "window_end"):
            _require_omitted(payload, field)
        bay_code = None
        window_start = window_end = None
        start_dt = end_dt = None

    existing = calc.tasks_of_vehicle(vehicle["id"])
    for row in existing:
        if row["task_type"] == task_type and row["status"] != "WAIVED":
            raise ApiError(
                "ERR_DUPLICATE_TASK_TYPE",
                "The vehicle already holds a non-waived %s task." % task_type,
            )

    if vehicle["fleet_status"] != "IN_FLEETING":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "In-fleeting tasks may only be scheduled for an IN_FLEETING vehicle.",
        )

    if task_type == "PREPARATION":
        for required in ("REGISTRATION", "LICENSING"):
            if not any(
                row["task_type"] == required and row["status"] in ("COMPLETED", "WAIVED")
                for row in existing
            ):
                raise ApiError(
                    "ERR_PREP_BEFORE_REGISTRATION",
                    "REGISTRATION and LICENSING must both be resolved before PREPARATION.",
                )
        if start_dt >= end_dt:
            raise ApiError(
                "ERR_INVALID_WINDOW",
                "window_start must fall strictly before window_end.",
            )
        _check_bay_conflict(vehicle, bay_code, start_dt, end_dt)
        _check_daily_capacity(vehicle, start_dt)

    row = base_row()
    row.update({
        "vehicle_id": vehicle["id"],
        "market_id": vehicle["current_market_id"],
        "task_type": task_type,
        "cost_cents": cost_cents,
        "bay_code": bay_code,
        "window_start": window_start,
        "window_end": window_end,
        "completed_at": None,
        "status": "PENDING",
    })
    store.tasks[row["id"]] = row
    return created(serialize.task(row))


def _check_bay_conflict(vehicle, bay_code, start_dt, end_dt):
    """Closed interval expanded by 60 minutes at each end; touching conflicts."""
    expanded_start = start_dt - BUFFER
    expanded_end = end_dt + BUFFER
    for row in store.tasks.values():
        if row["task_type"] != "PREPARATION" or row["status"] not in PREP_ACTIVE_STATUSES:
            continue
        if row["market_id"] != vehicle["current_market_id"] or row["bay_code"] != bay_code:
            continue
        other_start = parse_instant(row["window_start"])
        other_end = parse_instant(row["window_end"])
        if other_start is None or other_end is None:
            continue
        if expanded_start <= other_end and other_start <= expanded_end:
            raise ApiError(
                "ERR_PREP_BAY_CONFLICT",
                "The bay is already occupied within the buffered window.",
            )


def _check_daily_capacity(vehicle, start_dt):
    market = store.markets.get(vehicle["current_market_id"])
    if market is None:
        return
    target_date = start_dt.date()
    count = 0
    for row in store.tasks.values():
        if row["task_type"] != "PREPARATION" or row["status"] not in PREP_ACTIVE_STATUSES:
            continue
        if row["market_id"] != market["id"]:
            continue
        other_start = parse_instant(row["window_start"])
        if other_start is not None and other_start.date() == target_date:
            count += 1
    if count + 1 > market["prep_capacity_per_day"]:
        raise ApiError(
            "ERR_PREP_CAPACITY_EXCEEDED",
            "The market's daily preparation capacity is exhausted for that date.",
        )


@bp.route("/fleet/in-fleeting-tasks/<task_id>", methods=["GET"])
def read_task(task_id):
    authorize(ALL_ROLES)
    return ok(serialize.task(validate.load("task", task_id)))


@bp.route("/fleet/in-fleeting-tasks", methods=["GET"])
def list_tasks():
    authorize(ALL_ROLES)
    return collect(
        store.tasks.values(),
        [
            ("vehicle_id", "vehicle_id", "str"),
            ("market_id", "market_id", "str"),
            ("task_type", "task_type", "str"),
            ("status", "status", "str"),
        ],
        serialize.task,
    )


def _resolve(task, status, post_cost):
    vehicle = store.vehicles[task["vehicle_id"]]
    if task["status"] != "PENDING":
        raise ApiError(
            "ERR_TASK_ALREADY_RESOLVED",
            "The task has already been completed or waived.",
        )
    if vehicle["fleet_status"] != "IN_FLEETING":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "The task's vehicle is no longer IN_FLEETING.",
        )

    task["status"] = status
    task["completed_at"] = store.now_iso()
    touch(task)
    if post_cost:
        cascade.post_ledger(
            vehicle["id"],
            "PREP_COST",
            task["cost_cents"],
            "InFleetingTask",
            task["id"],
            "%s task cost" % task["task_type"].lower(),
        )
    cascade.stamp_milestone(vehicle, task["task_type"])
    cascade.evaluate_promotion(vehicle)
    return ok(serialize.task(task))


@bp.route("/fleet/in-fleeting-tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    actor, _role = authorize(("MarketOperator",))
    task = validate.load("task", task_id)
    require_scope(actor, task["market_id"])
    return _resolve(task, "COMPLETED", True)


@bp.route("/fleet/in-fleeting-tasks/<task_id>/waive", methods=["POST"])
def waive_task(task_id):
    authorize(("FleetController",))
    task = validate.load("task", task_id)
    return _resolve(task, "WAIVED", False)

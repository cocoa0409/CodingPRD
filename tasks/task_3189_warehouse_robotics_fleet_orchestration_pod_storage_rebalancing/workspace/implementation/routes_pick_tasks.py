"""Pick tasks blueprint: create, sequence (OCC), dispatch, deliver, begin-pick, complete, cancel."""

from flask import Blueprint, request

import errors
from calculations import (
    BATTERY_MIN_DISPATCH,
    DISRUPTION_WEIGHT,
    FATIGUE_WEIGHT,
    LATENESS_WEIGHT,
    STATION_BASE_RATE_SECONDS,
    fleet_selector_score,
    travel_cost_estimate,
)
from cascades import (
    cancel_pick_task_with_release,
    entity_out,
    find_slot,
    list_out,
    recompute_pod_slots_used,
    recompute_sku_counters,
)
from db import store
from middleware import require_roles
from models import base_entity, bump, get_or_404, req_int, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("pick_tasks", __name__)

READ_ROLES = {"FleetAdmin", "FlowController", "StationOperator", "FloorSupervisor"}


def _line_sku(line):
    return store.skus.get(line["sku_id"])


@bp.route("/pick-tasks", methods=["POST"])
def create_pick_task():
    require_roles({"FlowController"})
    body = request.get_json(silent=True) or {}
    order_id = require_field(body, "order_id")
    line_id = require_field(body, "line_id")
    pod_id = require_field(body, "pod_id")
    station_id = require_field(body, "station_id")
    for k, v in (
        ("order_id", order_id),
        ("line_id", line_id),
        ("pod_id", pod_id),
        ("station_id", station_id),
    ):
        if not isinstance(v, str):
            raise errors.validation(f"{k} must be a string")
    quantity = req_int(body, "quantity", minimum=1)
    order = get_or_404(store.orders, order_id, "customer order")
    line = get_or_404(store.order_lines, line_id, "order line")
    pod = get_or_404(store.pods, pod_id, "pod")
    station = get_or_404(store.pick_stations, station_id, "pick station")
    if line["order_id"] != order["id"]:
        raise errors.referential_mismatch("line does not belong to order")
    sku = _line_sku(line)
    line_remainder = line["quantity"] - line["quantity_picked"]
    sku_available = sku["total_units_on_hand"] - sku["total_units_reserved"]
    if sku_available < line_remainder:
        raise errors.insufficient_inventory(
            "sku-wide availability below line remainder"
        )
    task = base_entity()
    task.update(
        {
            "order_id": order_id,
            "line_id": line_id,
            "pod_id": pod_id,
            "station_id": station_id,
            "drive_unit_id": None,
            "quantity": quantity,
            "status": "CREATED",
            "sequence_index": None,
            "est_cost": None,
            "actual_cost": None,
        }
    )
    store.pick_tasks[task["id"]] = task
    return success_object(entity_out(task), status=201)


@bp.route("/pick-tasks", methods=["GET"])
def list_pick_tasks():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.pick_tasks.values())
    for key in ("order_id", "line_id", "pod_id", "station_id", "drive_unit_id", "status"):
        f = request.args.get(key)
        if f is not None:
            items = [t for t in items if t.get(key) == f]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/pick-tasks/<task_id>", methods=["GET"])
def get_pick_task(task_id):
    require_roles(READ_ROLES)
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    return success_object(entity_out(task))


def _station_completed_today(station_id):
    return sum(
        1
        for t in store.pick_tasks.values()
        if t["station_id"] == station_id and t["status"] == "COMPLETE"
    )


def _sequence_index(station, order):
    """Workload-smoothing sequencer per PRD 3.3."""
    queued = sorted(
        (
            t
            for t in store.pick_tasks.values()
            if t["station_id"] == station["id"] and t["status"] in {"QUEUED", "DELIVERED"}
        ),
        key=lambda t: t.get("sequence_index") or 0,
    )
    n = len(queued)
    cutoff_dt = order.get("_cutoff_dt")
    if cutoff_dt is not None:
        seconds_until = (cutoff_dt - store.clock).total_seconds()
    else:
        seconds_until = float("inf")
    completed_today = _station_completed_today(station["id"])
    best_k = 0
    best_score = None
    for k in range(0, n + 1):
        est_finish = STATION_BASE_RATE_SECONDS * (k + 1)
        if seconds_until == float("inf"):
            lateness = 0
        else:
            lateness = max(0, est_finish - seconds_until)
        disruption = 0
        for idx, t in enumerate(queued):
            old_idx = t.get("sequence_index") or idx
            new_idx = idx if idx < k else idx + 1
            disruption += abs(old_idx - new_idx)
        fatigue = completed_today * FATIGUE_WEIGHT * k
        score = (
            LATENESS_WEIGHT * lateness
            + DISRUPTION_WEIGHT * disruption
            + fatigue
        )
        if best_score is None or score < best_score:
            best_score = score
            best_k = k
        # ties -> larger k (strict less-than keeps the larger k when equal? No:
        # equal score keeps the earlier k found; to prefer LARGER k on tie, use <=)
        elif score == best_score:
            best_k = k
    # Shift existing queued tasks at positions >= best_k up by one.
    for t in queued:
        cur = t.get("sequence_index") or 0
        if cur >= best_k:
            t["sequence_index"] = cur + 1
            bump(t)
    return best_k


@bp.route("/pick-tasks/<task_id>/sequence", methods=["POST"])
def sequence_pick_task(task_id):
    require_roles({"FlowController"})
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    body = request.get_json(silent=True) or {}
    if task["status"] != "CREATED":
        raise errors.invalid_state("pick task is not CREATED")
    station = store.pick_stations.get(task["station_id"])
    pod = store.pods.get(task["pod_id"])
    line = store.order_lines.get(task["line_id"])
    order = store.orders.get(task["order_id"])
    if station is None or pod is None or line is None or order is None:
        raise errors.not_found("referenced entity missing")
    # Safety interlock: FROZEN pod zone (before capacity, per PRD §2.6).
    pod_zone = store.zones.get(pod["zone_id"])
    if pod_zone is not None and pod_zone.get("posture") == "FROZEN":
        raise errors.safety_interlock("pod zone is FROZEN")
    if station["status"] != "OPEN":
        raise errors.invalid_state("pick station is not OPEN")
    if pod["status"] not in {"IN_STORAGE", "RESERVED"}:
        raise errors.invalid_state("pod is not IN_STORAGE or RESERVED")
    if station["queue_length"] >= station["max_queue"]:
        raise errors.capacity_exceeded("station queue full")
    slot = find_slot(pod["id"], line["sku_id"])
    available = (slot["quantity"] - slot["quantity_reserved"]) if slot is not None else 0
    if available < task["quantity"]:
        raise errors.insufficient_inventory("slot availability below task quantity")
    expected = body.get("expected_station_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise errors.validation("expected_station_version must be an integer")
        if expected != station["version"]:
            raise errors.stale_version("station version mismatch")
    seq = _sequence_index(station, order)
    task["sequence_index"] = seq
    task["status"] = "QUEUED"
    bump(task)
    station["queue_length"] += 1
    bump(station)
    if pod["status"] == "IN_STORAGE":
        pod["status"] = "RESERVED"
        bump(pod)
    if slot is not None:
        slot["quantity_reserved"] += task["quantity"]
        bump(slot)
    sku = store.skus.get(line["sku_id"])
    if sku is not None:
        recompute_sku_counters(sku)
        bump(sku)
    if order["status"] == "RECEIVED":
        order["status"] = "PLANNED"
        bump(order)
    return success_object(entity_out(task))


def _unit_dispatch_eligible(unit):
    if unit["status"] != "ACTIVE":
        return False
    if unit["battery_pct"] < BATTERY_MIN_DISPATCH:
        return False
    now = store.clock
    for w in store.maintenance_windows.values():
        if w["drive_unit_id"] != unit["id"]:
            continue
        if w["status"] != "ACTIVE":
            continue
        return False
    home_zone = store.zones.get(unit["home_zone_id"])
    if home_zone is not None and home_zone.get("posture") == "FROZEN":
        return False
    return True


@bp.route("/pick-tasks/<task_id>/dispatch", methods=["POST"])
def dispatch_pick_task(task_id):
    require_roles({"FlowController"})
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    if task["status"] != "QUEUED":
        raise errors.invalid_state("pick task is not QUEUED")
    pod = store.pods.get(task["pod_id"])
    if pod is None:
        raise errors.not_found("pod missing")
    candidates = [u for u in store.drive_units.values() if _unit_dispatch_eligible(u)]
    if not candidates:
        raise errors.no_eligible_drive_unit()
    # Highest score; tie-break created_at ASC.
    candidates.sort(key=lambda u: u["created_at"])
    best = None
    best_score = None
    for u in candidates:
        s = fleet_selector_score(u, pod)
        if best is None or s > best_score:
            best = u
            best_score = s
    task["drive_unit_id"] = best["id"]
    task["status"] = "DISPATCHED"
    est = travel_cost_estimate(task, "planning", carrying_unit=best)
    task["est_cost"] = float(est)
    bump(task)
    best["status"] = "EN_ROUTE"
    bump(best)
    return success_object(entity_out(task))


@bp.route("/pick-tasks/<task_id>/deliver", methods=["POST"])
def deliver_pick_task(task_id):
    require_roles({"FlowController"})
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    if task["status"] != "DISPATCHED":
        raise errors.invalid_state("pick task is not DISPATCHED")
    unit = store.drive_units.get(task.get("drive_unit_id"))
    if unit is None:
        raise errors.not_found("drive unit missing")
    actual = travel_cost_estimate(task, "execution", carrying_unit=unit)
    task["actual_cost"] = float(actual)
    task["status"] = "DELIVERED"
    bump(task)
    unit["battery_pct"] = max(0, int(unit["battery_pct"] - int(actual)))
    unit["odometer_cells"] = unit["odometer_cells"] + int(actual)
    unit["status"] = "AT_STATION"
    bump(unit)
    pod = store.pods.get(task["pod_id"])
    if pod is not None:
        pod["status"] = "AT_STATION"
        bump(pod)
    return success_object(entity_out(task))


@bp.route("/pick-tasks/<task_id>/begin-pick", methods=["POST"])
def begin_pick(task_id):
    require_roles({"StationOperator"})
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    if task["status"] != "DELIVERED":
        raise errors.invalid_state("pick task is not DELIVERED")
    plan_date = store.clock.strftime("%Y-%m-%d")
    plan = None
    for p in store.shift_plans.values():
        if p["plan_date"] == plan_date:
            plan = p
            break
    if plan is None or plan.get("staffed_pickers", 0) <= 0:
        raise errors.invalid_state("no rostered pickers on current shift plan")
    task["status"] = "PICKING"
    bump(task)
    return success_object(entity_out(task))


@bp.route("/pick-tasks/<task_id>/complete", methods=["POST"])
def complete_pick(task_id):
    require_roles({"StationOperator"})
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    if task["status"] != "PICKING":
        raise errors.invalid_state("pick task is not PICKING")
    line = store.order_lines.get(task["line_id"])
    pod = store.pods.get(task["pod_id"])
    station = store.pick_stations.get(task["station_id"])
    order = store.orders.get(task["order_id"])
    unit = store.drive_units.get(task.get("drive_unit_id"))
    slot = find_slot(task["pod_id"], line["sku_id"]) if line else None
    if slot is not None:
        slot["quantity"] = max(0, slot["quantity"] - task["quantity"])
        slot["quantity_reserved"] = max(0, slot["quantity_reserved"] - task["quantity"])
        bump(slot)
    if pod is not None:
        recompute_pod_slots_used(pod)
        pod["status"] = "IN_STORAGE"
        bump(pod)
    if line is not None:
        recompute_sku = store.skus.get(line["sku_id"])
        if recompute_sku is not None:
            recompute_sku_counters(recompute_sku)
            bump(recompute_sku)
        line["quantity_picked"] += task["quantity"]
        bump(line)
    if station is not None:
        station["queue_length"] = max(0, station["queue_length"] - 1)
        bump(station)
    if unit is not None:
        unit["status"] = "ACTIVE"
        bump(unit)
    task["status"] = "COMPLETE"
    bump(task)
    if order is not None:
        if order["status"] == "PLANNED":
            order["status"] = "IN_PROGRESS"
            bump(order)
        all_lines = [ln for ln in store.order_lines.values() if ln["order_id"] == order["id"]]
        if all_lines and all(ln["quantity_picked"] >= ln["quantity"] for ln in all_lines):
            if order["status"] in {"PLANNED", "IN_PROGRESS"}:
                order["status"] = "COMPLETE"
                bump(order)
    from calculations import recompute_shift_plans

    recompute_shift_plans()
    return success_object(entity_out(task))


@bp.route("/pick-tasks/<task_id>/cancel", methods=["POST"])
def cancel_pick(task_id):
    require_roles({"FlowController"})
    task = get_or_404(store.pick_tasks, task_id, "pick task")
    if task["status"] not in {"CREATED", "QUEUED"}:
        raise errors.invalid_state("pick task is not CREATED or QUEUED")
    cancel_pick_task_with_release(task)
    from calculations import recompute_shift_plans

    recompute_shift_plans()
    return success_object(entity_out(task))

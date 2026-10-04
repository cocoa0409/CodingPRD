"""Stow tasks blueprint."""

from flask import Blueprint, request

import errors
from calculations import stow_density_score
from cascades import entity_out, find_slot, list_out, recompute_pod_slots_used
from db import store
from middleware import require_roles
from models import base_entity, bump, get_or_404, req_int, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("stow_tasks", __name__)

READ_ROLES = {"FleetAdmin", "FlowController", "StationOperator"}


@bp.route("/stow-tasks", methods=["POST"])
def create_stow_task():
    require_roles({"FlowController"})
    body = request.get_json(silent=True) or {}
    sku_id = require_field(body, "sku_id")
    if not isinstance(sku_id, str):
        raise errors.validation("sku_id must be a string")
    get_or_404(store.skus, sku_id, "sku")
    quantity = req_int(body, "quantity", minimum=1)
    task = base_entity()
    task.update(
        {
            "sku_id": sku_id,
            "quantity": quantity,
            "pod_id": None,
            "status": "PENDING",
            "placement_score": None,
        }
    )
    store.stow_tasks[task["id"]] = task
    return success_object(entity_out(task), status=201)


@bp.route("/stow-tasks", methods=["GET"])
def list_stow_tasks():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.stow_tasks.values())
    for key in ("sku_id", "pod_id", "status"):
        f = request.args.get(key)
        if f is not None:
            items = [t for t in items if t.get(key) == f]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/stow-tasks/<task_id>", methods=["GET"])
def get_stow_task(task_id):
    require_roles(READ_ROLES)
    task = get_or_404(store.stow_tasks, task_id, "stow task")
    return success_object(entity_out(task))


def _eligible_pod(pod, sku_id):
    if pod["status"] not in {"IN_STORAGE", "RESERVED"}:
        return False
    zone = store.zones.get(pod["zone_id"])
    if zone is not None and zone.get("posture") == "FROZEN":
        return False
    if find_slot(pod["id"], sku_id) is not None:
        return True
    return pod["slots_used"] < pod["slot_capacity"]


@bp.route("/stow-tasks/<task_id>/place", methods=["POST"])
def place_stow_task(task_id):
    require_roles({"FlowController"})
    task = get_or_404(store.stow_tasks, task_id, "stow task")
    body = request.get_json(silent=True) or {}
    if task["status"] != "PENDING":
        raise errors.invalid_state("stow task is not PENDING")
    sku = store.skus.get(task["sku_id"])
    if sku is None:
        raise errors.not_found("sku missing")
    expected = body.get("expected_sku_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise errors.validation("expected_sku_version must be an integer")
        if expected != sku["version"]:
            raise errors.stale_version("sku version mismatch")
    candidates = [p for p in store.pods.values() if _eligible_pod(p, sku["id"])]
    if not candidates:
        task["status"] = "REJECTED"
        bump(task)
        raise errors.no_eligible_pod()
    candidates.sort(key=lambda p: p["created_at"])
    best = None
    best_score = None
    for p in candidates:
        s = stow_density_score(p, sku)
        if best is None or s > best_score:
            best = p
            best_score = s
    task["pod_id"] = best["id"]
    task["placement_score"] = float(best_score)
    task["status"] = "PLACED"
    bump(task)
    if best["status"] == "IN_STORAGE":
        best["status"] = "RESERVED"
        bump(best)
    bump(sku)
    return success_object(entity_out(task))


@bp.route("/stow-tasks/<task_id>/confirm", methods=["POST"])
def confirm_stow_task(task_id):
    require_roles({"StationOperator"})
    task = get_or_404(store.stow_tasks, task_id, "stow task")
    if task["status"] != "PLACED":
        raise errors.invalid_state("stow task is not PLACED")
    pod = store.pods.get(task["pod_id"])
    sku = store.skus.get(task["sku_id"])
    if pod is None or sku is None:
        raise errors.not_found("referenced entity missing")
    slot = find_slot(pod["id"], sku["id"])
    if slot is None:
        if pod["slots_used"] >= pod["slot_capacity"]:
            raise errors.capacity_exceeded("pod at capacity for a new slot")
        slot = base_entity()
        slot.update(
            {
                "pod_id": pod["id"],
                "sku_id": sku["id"],
                "quantity": 0,
                "quantity_reserved": 0,
                "accessibility_rank": 1,
            }
        )
        store.inventory_slots[slot["id"]] = slot
    slot["quantity"] += task["quantity"]
    bump(slot)
    recompute_pod_slots_used(pod)
    sku["total_units_on_hand"] = sku["total_units_on_hand"] + task["quantity"]
    bump(sku)
    if pod["status"] == "RESERVED":
        pod["status"] = "IN_STORAGE"
    bump(pod)
    task["status"] = "COMPLETE"
    bump(task)
    return success_object(entity_out(task))

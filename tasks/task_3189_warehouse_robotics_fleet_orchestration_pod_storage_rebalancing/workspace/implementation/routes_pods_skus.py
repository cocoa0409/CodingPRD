"""Pods, SKUs, and inventory slots blueprint."""

from flask import Blueprint, request

import errors
from cascades import entity_out, list_out
from db import store
from middleware import require_roles
from models import base_entity, get_or_404, req_enum, req_int, req_str, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("pods_skus", __name__)

POD_READ_ROLES = {"FleetAdmin", "FlowController", "FloorSupervisor", "StationOperator"}
SKU_READ_ROLES = {"FleetAdmin", "FlowController", "StationOperator"}


@bp.route("/pods", methods=["POST"])
def create_pod():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    pod_code = req_str(body, "pod_code")
    zone_id = require_field(body, "zone_id")
    if not isinstance(zone_id, str):
        raise errors.validation("zone_id must be a string")
    get_or_404(store.zones, zone_id, "zone")
    slot_capacity = req_int(body, "slot_capacity", minimum=1)
    for p in store.pods.values():
        if p["pod_code"] == pod_code:
            raise errors.validation(f"pod_code already exists: {pod_code}")
    pod = base_entity()
    pod.update(
        {
            "pod_code": pod_code,
            "zone_id": zone_id,
            "slot_capacity": slot_capacity,
            "slots_used": 0,
            "status": "IN_STORAGE",
        }
    )
    store.pods[pod["id"]] = pod
    return success_object(entity_out(pod), status=201)


@bp.route("/pods/<pod_id>", methods=["GET"])
def get_pod(pod_id):
    require_roles(POD_READ_ROLES)
    pod = get_or_404(store.pods, pod_id, "pod")
    return success_object(entity_out(pod))


@bp.route("/pods/<pod_id>/inventory-slots", methods=["GET"])
def pod_slots(pod_id):
    require_roles({"FleetAdmin", "FlowController", "StationOperator"})
    get_or_404(store.pods, pod_id, "pod")
    limit, offset = parse_pagination()
    items = sorted(
        (s for s in store.inventory_slots.values() if s["pod_id"] == pod_id),
        key=lambda s: s["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/skus", methods=["POST"])
def create_sku():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    sku_code = req_str(body, "sku_code")
    velocity_class = req_enum(body, "velocity_class", {"HIGH", "MEDIUM", "LOW"})
    for s in store.skus.values():
        if s["sku_code"] == sku_code:
            raise errors.validation(f"sku_code already exists: {sku_code}")
    sku = base_entity()
    sku.update(
        {
            "sku_code": sku_code,
            "velocity_class": velocity_class,
            "total_units_on_hand": 0,
            "total_units_reserved": 0,
        }
    )
    store.skus[sku["id"]] = sku
    return success_object(entity_out(sku), status=201)


@bp.route("/skus", methods=["GET"])
def list_skus():
    require_roles(SKU_READ_ROLES)
    limit, offset = parse_pagination()
    velocity_f = request.args.get("velocity_class")
    items = list(store.skus.values())
    if velocity_f is not None:
        items = [s for s in items if s["velocity_class"] == velocity_f]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/skus/<sku_id>", methods=["GET"])
def get_sku(sku_id):
    require_roles(SKU_READ_ROLES)
    sku = get_or_404(store.skus, sku_id, "sku")
    return success_object(entity_out(sku))


@bp.route("/skus/<sku_id>/inventory-slots", methods=["GET"])
def sku_slots(sku_id):
    require_roles(SKU_READ_ROLES)
    get_or_404(store.skus, sku_id, "sku")
    limit, offset = parse_pagination()
    items = sorted(
        (s for s in store.inventory_slots.values() if s["sku_id"] == sku_id),
        key=lambda s: s["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/skus/<sku_id>/order-lines", methods=["GET"])
def sku_order_lines(sku_id):
    require_roles(SKU_READ_ROLES)
    get_or_404(store.skus, sku_id, "sku")
    limit, offset = parse_pagination()
    items = sorted(
        (ln for ln in store.order_lines.values() if ln["sku_id"] == sku_id),
        key=lambda ln: ln["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/inventory-slots", methods=["GET"])
def list_inventory_slots():
    require_roles(SKU_READ_ROLES)
    limit, offset = parse_pagination()
    pod_f = request.args.get("pod_id")
    sku_f = request.args.get("sku_id")
    items = list(store.inventory_slots.values())
    if pod_f is not None:
        items = [s for s in items if s["pod_id"] == pod_f]
    if sku_f is not None:
        items = [s for s in items if s["sku_id"] == sku_f]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/order-lines", methods=["GET"])
def list_order_lines():
    require_roles(SKU_READ_ROLES)
    limit, offset = parse_pagination()
    order_f = request.args.get("order_id")
    sku_f = request.args.get("sku_id")
    items = list(store.order_lines.values())
    if order_f is not None:
        items = [ln for ln in items if ln["order_id"] == order_f]
    if sku_f is not None:
        items = [ln for ln in items if ln["sku_id"] == sku_f]
    items.sort(key=lambda ln: ln["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)

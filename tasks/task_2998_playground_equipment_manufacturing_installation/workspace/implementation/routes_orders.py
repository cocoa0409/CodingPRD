"""Manufacturing orders and the fork-join production floor (PRD section 3.7)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import public, public_list, store

bp = Blueprint("orders", __name__)

ORDER_READ_ROLES = [
    "ManufacturerAdmin",
    "ComplianceOfficer",
    "DesignConsultant",
    "ClientRepresentative",
    "InstallerOperator",
]
PREP_STATUSES = ("PENDING", "IN_PROGRESS", "DONE")
PREP_TRANSITIONS = {
    ("PENDING", "IN_PROGRESS"),
    ("PENDING", "DONE"),
    ("IN_PROGRESS", "DONE"),
}


@bp.route("/playground/orders", methods=["POST"])
def create_order():
    authenticate(["DesignConsultant"])
    body = v.raw_body()
    resolved = v.resolve_fks(body, [("quote_id", "quote", True)])
    v.string(body, "quote_id", min_len=1)
    quote = resolved["quote_id"]
    project = store.require("project", quote["project_id"])

    if project["design_status"] != "CERTIFIED":
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    if quote["status"] != "ACCEPTED" or quote["variant"] != "FIRM":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED")

    for placement in store.project_placements(project["id"]):
        if placement["status"] != "VALIDATED":
            raise ApiError("ERR_PLACEMENTS_NOT_VALIDATED")

    if project["funds_collected_cents"] < quote["total_cents"]:
        raise ApiError("ERR_FUNDING_SHORTFALL")

    row = store.insert("order", {
        "quote_id": quote["id"],
        "production_status": "CREATED",
        "kitting_status": "PENDING",
        "bagging_status": "PENDING",
        "kit_line_count": 0,
        "hardware_bag_total": 0,
        "instruction_package_revision": 0,
    })

    project["design_status"] = "ORDERED"
    store.touch(project)
    for area in store.project_areas(project["id"]):
        if area["status"] != "LOCKED":
            area["status"] = "LOCKED"
            store.touch(area)
    return object_response(public(row), 201)


@bp.route("/playground/orders", methods=["GET"])
def list_orders():
    authenticate(ORDER_READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("order"), {
        "quote_id": "quote_id",
        "production_status": "production_status",
        "kitting_status": "kitting_status",
        "bagging_status": "bagging_status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    authenticate(ORDER_READ_ROLES)
    return object_response(public(store.require("order", order_id)))


@bp.route("/playground/orders/<order_id>/start-production", methods=["POST"])
def start_production(order_id):
    authenticate(["ManufacturerAdmin"])
    order = store.require("order", order_id)
    if order["production_status"] != "CREATED":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    project = store.order_project(order)
    if project is None or project["design_status"] != "ORDERED":
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    order["production_status"] = "IN_PRODUCTION"
    store.touch(order)
    return object_response(public(order))


def _advance_prep(order, field, target):
    """Shared prep-dimension advance plus the join into READY_TO_SHIP."""
    if order["production_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_ORDER_NOT_IN_PRODUCTION")
    if (order[field], target) not in PREP_TRANSITIONS:
        raise ApiError("ERR_ORDER_INVALID_STATE")
    order[field] = target

    if target == "DONE":
        if field == "kitting_status":
            order["kit_line_count"] = len(calc.priced_placements_for_order(order))
        else:
            order["hardware_bag_total"] = calc.hardware_bag_total(order)

    if order["kitting_status"] == "DONE" and order["bagging_status"] == "DONE":
        order["production_status"] = "READY_TO_SHIP"
        quote = store.get("quote", order["quote_id"])
        rendering = store.get("rendering", quote["rendering_id"]) if quote else None
        order["instruction_package_revision"] = rendering["round_number"] if rendering else 0

    store.touch(order)
    return object_response(public(order))


@bp.route("/playground/orders/<order_id>/kitting", methods=["POST"])
def advance_kitting(order_id):
    authenticate(["ManufacturerAdmin"])
    order = store.require("order", order_id)
    body = v.raw_body()
    target = v.enum(body, "kitting_status", PREP_STATUSES)
    return _advance_prep(order, "kitting_status", target)


@bp.route("/playground/orders/<order_id>/hardware-bagging", methods=["POST"])
def advance_bagging(order_id):
    authenticate(["ManufacturerAdmin"])
    order = store.require("order", order_id)
    body = v.raw_body()
    target = v.enum(body, "bagging_status", PREP_STATUSES)
    return _advance_prep(order, "bagging_status", target)


@bp.route("/playground/orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    authenticate(["ManufacturerAdmin"])
    order = store.require("order", order_id)
    if order["production_status"] != "READY_TO_SHIP":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    order["production_status"] = "SHIPPED"
    store.touch(order)
    return object_response(public(order))

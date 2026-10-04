"""ChangeOrder lifecycle (PRD 3.5): PENDING -> APPROVED / REJECTED."""
from flask import Blueprint, request

from auth import enforce_vendor_ownership, require_roles
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_ADVANCE_LIMIT_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from logic import (
    bump,
    get_or_404,
    list_response,
    new_record,
    project_change_orders,
    serialize,
)
from validate import body_json, req_enum, req_int, req_str

bp = Blueprint("change_orders", __name__)

CHANGE_ORDER_REASONS = ("SCOPE_CREEP", "HIDDEN_DAMAGE", "MATERIAL_PRICE", "CODE_UPGRADE", "OTHER")


@bp.post("/concierge/change-orders")
@require_roles("Vendor")
def create_change_order():
    body = body_json(required=True)
    project = get_or_404(store.projects, req_str(body, "improvement_project_id"), "ImprovementProject")
    eng = get_or_404(store.engagements, req_str(body, "vendor_engagement_id"), "VendorEngagement")
    if eng["improvement_project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, "VendorEngagement does not belong to the project", 404)
    enforce_vendor_ownership(eng["vendor_id"])
    delta = req_int(body, "delta_cents")
    reason = req_enum(body, "reason", CHANGE_ORDER_REASONS)
    rec = new_record({
        "improvement_project_id": project["id"],
        "vendor_engagement_id": eng["id"],
        "delta_cents": delta,
        "reason": reason,
        "status": "PENDING",
    })
    store.change_orders[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/change-orders/<changeOrderId>")
@require_roles("Any")
def get_change_order(changeOrderId):
    return success_obj(serialize(get_or_404(store.change_orders, changeOrderId, "ChangeOrder")))


@bp.get("/concierge/change-orders")
@require_roles("Any")
def list_change_orders():
    items = list(store.change_orders.values())
    pid = request.args.get("improvement_project_id")
    if pid is not None:
        items = [c for c in items if c["improvement_project_id"] == pid]
    return list_response(items)


@bp.get("/concierge/projects/<projectId>/change-orders")
@require_roles("Any")
def list_project_change_orders(projectId):
    get_or_404(store.projects, projectId, "ImprovementProject")
    return list_response(project_change_orders(projectId))


@bp.post("/concierge/change-orders/<changeOrderId>/approve")
@require_roles("Homeowner")
def approve_change_order(changeOrderId):
    co = get_or_404(store.change_orders, changeOrderId, "ChangeOrder")
    if co["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "ChangeOrder is not PENDING", 409)
    project = store.projects[co["improvement_project_id"]]
    case = store.cases[project["concierge_case_id"]]
    if project["status"] not in ("SCHEDULED", "IN_WORK"):
        raise ApiError(ERR_INVALID_STATE, "Project is not SCHEDULED or IN_WORK", 409)
    if case["advance_total_cents"] + co["delta_cents"] > case["advance_limit_cents"]:
        raise ApiError(ERR_ADVANCE_LIMIT_EXCEEDED, "Change order exceeds advance-limit headroom", 409)
    co["status"] = "APPROVED"
    bump(co)
    # cost_overrun = max(0, sum of APPROVED deltas) - approved_cost_cents (pinned formula).
    total_delta = sum(
        c["delta_cents"] for c in project_change_orders(project["id"]) if c["status"] == "APPROVED"
    )
    project["cost_overrun_cents"] = max(0, total_delta) - project["approved_cost_cents"]
    bump(project)
    case["advance_total_cents"] += co["delta_cents"]
    bump(case)
    return success_obj(serialize(co))


@bp.post("/concierge/change-orders/<changeOrderId>/reject")
@require_roles("Homeowner")
def reject_change_order(changeOrderId):
    co = get_or_404(store.change_orders, changeOrderId, "ChangeOrder")
    if co["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "ChangeOrder is not PENDING", 409)
    co["status"] = "REJECTED"
    bump(co)
    return success_obj(serialize(co))

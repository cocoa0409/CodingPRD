"""RiggingPlan and RiggingAllocation endpoints."""
from flask import Blueprint, request

from constants import ALL_ROLES, HIGH_RISK_DYNAMIC_KG
from db import db, base_fields, touch
from errors import err
from middleware import require_roles, current_user
from response import success, paginate
import helpers as H
import ticks

bp = Blueprint("rigging", __name__)


def _plan_rollups(plan):
    allocs = [a for a in db.rigging_allocations.values()
              if a["rigging_plan_id"] == plan["id"]]
    plan["aggregate_static_load_kg"] = sum(a["static_load_kg"] for a in allocs)
    plan["max_dynamic_point_load_kg"] = max([a["dynamic_load_kg"] for a in allocs] or [0])
    high = False
    for a in allocs:
        if a["dynamic_load_kg"] > HIGH_RISK_DYNAMIC_KG:
            high = True
            break
        pt = db.rigging_points.get(a["rigging_point_id"])
        if pt is not None and pt.get("engineering_review_required"):
            high = True
            break
    plan["high_risk_review_required"] = high


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans", methods=["POST"])
@require_roles("ProductionEngineer")
def create_plan(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    for p in db.rigging_plans.values():
        if p["engagement_id"] == e["id"] and p["status"] in H.PLAN_NONTERMINAL:
            p["status"] = "SUPERSEDED"
            touch(p)
    plan = base_fields()
    plan.update({
        "engagement_id": e["id"],
        "status": "DRAFT",
        "revision_no": 1,
        "submitted_at": None,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "max_dynamic_point_load_kg": 0,
        "aggregate_static_load_kg": 0,
        "high_risk_review_required": False,
    })
    db.rigging_plans[plan["id"]] = plan
    return success(plan, 201)


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plans(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    items = [p for p in db.rigging_plans.values() if p["engagement_id"] == engagementId]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan(tourId, engagementId, planId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    return success(H.get_plan(tourId, engagementId, planId))


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>/submit", methods=["POST"])
@require_roles("ProductionEngineer")
def submit_plan(tourId, engagementId, planId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    plan = H.get_plan(tourId, engagementId, planId)
    if plan["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Plan must be DRAFT to submit")
    allocs = [a for a in db.rigging_allocations.values()
              if a["rigging_plan_id"] == plan["id"]]
    if not allocs:
        raise err("ERR_EMPTY_RIGGING_PLAN", "Plan has no allocations")
    _plan_rollups(plan)
    plan["status"] = "SUBMITTED"
    from clock import now
    plan["submitted_at"] = now()
    uid, _role = current_user()
    plan["submitted_by_user_id"] = uid
    touch(plan)
    return success(plan)


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>/approve", methods=["POST"])
@require_roles("ProductionEngineer")
def approve_plan(tourId, engagementId, planId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    plan = H.get_plan(tourId, engagementId, planId)
    if plan["status"] != "SUBMITTED":
        raise err("ERR_PLAN_NOT_SUBMITTED", "Plan must be SUBMITTED to approve")
    allocs = [a for a in db.rigging_allocations.values()
              if a["rigging_plan_id"] == plan["id"]]
    # capacity with same-point summing
    by_point = {}
    for a in allocs:
        by_point.setdefault(a["rigging_point_id"], []).append(a)
    for pid, group in by_point.items():
        pt = db.rigging_points.get(pid)
        if pt is None:
            raise err("ERR_POINT_NOT_FOUND", "RiggingPoint not found: %s" % pid)
        if pt["status"] != "AVAILABLE":
            raise err("ERR_POINT_OUT_OF_SERVICE", "Point %s is OUT_OF_SERVICE" % pid)
        if sum(a["static_load_kg"] for a in group) > pt["max_static_load_kg"]:
            raise err("ERR_POINT_CAPACITY_EXCEEDED", "Static load exceeds capacity on %s" % pid)
        if sum(a["dynamic_load_kg"] for a in group) > pt["max_dynamic_load_kg"]:
            raise err("ERR_POINT_CAPACITY_EXCEEDED", "Dynamic load exceeds capacity on %s" % pid)
    _plan_rollups(plan)
    uid, _role = current_user()
    if plan["high_risk_review_required"] and plan.get("submitted_by_user_id") == uid:
        raise err("ERR_NEEDS_INDEPENDENT_REVIEW",
                  "High-risk plan requires an independent approver")
    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = uid
    touch(plan)
    return success(plan)


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>/reject", methods=["POST"])
@require_roles("ProductionEngineer")
def reject_plan(tourId, engagementId, planId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    plan = H.get_plan(tourId, engagementId, planId)
    if plan["status"] != "SUBMITTED":
        raise err("ERR_PLAN_NOT_SUBMITTED", "Plan must be SUBMITTED to reject")
    plan["status"] = "REJECTED"
    touch(plan)
    return success(plan)


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>/revise", methods=["POST"])
@require_roles("ProductionEngineer")
def revise_plan(tourId, engagementId, planId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    plan = H.get_plan(tourId, engagementId, planId)
    if plan["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Plan must be REJECTED to revise")
    plan["status"] = "DRAFT"
    plan["revision_no"] += 1
    touch(plan)
    return success(plan)


# ---------- allocations ----------

@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>/allocations",
          methods=["POST"])
@require_roles("ProductionEngineer")
def create_allocation(tourId, engagementId, planId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    plan = H.get_plan(tourId, engagementId, planId)
    data = H.body()
    pid = data.get("rigging_point_id")
    if pid is not None:
        H.get_point(e["venue_id"], pid)
    H.require_fields(data, ["rigging_point_id", "static_load_kg", "purpose"])
    if plan["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Allocations may only be added to a DRAFT plan")
    a = base_fields()
    a.update({
        "rigging_plan_id": plan["id"],
        "rigging_point_id": pid,
        "static_load_kg": H.req_int(data, "static_load_kg"),
        "dynamic_load_kg": H.opt_int(data, "dynamic_load_kg", 0),
        "purpose": H.req_str(data, "purpose"),
    })
    db.rigging_allocations[a["id"]] = a
    _plan_rollups(plan)
    touch(plan)
    return success(a, 201)


@bp.route("/tours/<tourId>/engagements/<engagementId>/rigging-plans/<planId>/allocations",
          methods=["GET"])
@require_roles(*ALL_ROLES)
def list_allocations(tourId, engagementId, planId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    plan = H.get_plan(tourId, engagementId, planId)
    items = [a for a in db.rigging_allocations.values()
             if a["rigging_plan_id"] == plan["id"]]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)

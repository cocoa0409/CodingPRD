"""Material orders: pricing, the plan ledger and the procurement lifecycle."""

from flask import Blueprint, request

import calc
import domain
import store
import validation as v
from auth import ALL_ROLES, actor, require, role
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("material", __name__)

CATEGORIES = ("BRIDGE", "SIGNAGE", "TOOLS", "DRAINAGE", "SURFACING")
ORDER_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "DELIVERED", "CANCELLED")


def _settle_plan(plan):
    domain.recompute_ledger(plan)
    touch(plan)
    domain.propagate_budget(plan)


@bp.post("/material-orders")
@require("CrewLeader")
def create_order():
    data = v.body()
    work_plan_id = v.req_id(data, "work_plan_id")
    category = v.req_enum(data, "category", CATEGORIES)
    lines = v.req_lines(data, "lines")
    expected_version = v.req_int(data, "expected_work_plan_version")
    condition_report_id = v.opt_id(data, "condition_report_id")
    engineering_review_ref = v.opt_str(data, "engineering_review_ref")

    plan = domain.get_plan(work_plan_id)
    if condition_report_id is not None:
        domain.get_report(condition_report_id)

    if plan["status"] == "CLOSED":
        fail("ERR_INVALID_STATE", "The work plan is CLOSED.")

    if expected_version != int(plan["version"]):
        fail("ERR_STALE_WORK_PLAN_VERSION", "The work plan version is stale.")

    pricing = calc.price_material_order(lines, category)
    cap = calc.overcommit_cap(int(plan["approved_budget_cents"]))
    projected = int(plan["committed_cents"]) + int(plan["spent_cents"]) + pricing["total_cents"]
    if projected > cap:
        fail("ERR_PLAN_BUDGET_EXCEEDED", "The plan's admission cap would be exceeded.")

    order = new_entity({
        "work_plan_id": work_plan_id,
        "condition_report_id": condition_report_id,
        "category": category,
        "lines": lines,
        "line_subtotal_cents": pricing["line_subtotal_cents"],
        "discount_pct": pricing["discount_pct"],
        "discount_cents": pricing["discount_cents"],
        "discounted_subtotal_cents": pricing["discounted_subtotal_cents"],
        "freight_cents": pricing["freight_cents"],
        "bridge_surcharge_cents": pricing["bridge_surcharge_cents"],
        "total_cents": pricing["total_cents"],
        "status": "DRAFT",
        "engineering_review_ref": engineering_review_ref,
        "approved_by_user_id": None,
        "delivered_at": None,
        "cancellation_reason": None,
    })
    store.orders[order["id"]] = order
    _settle_plan(plan)
    return created(domain.s_order(order))


@bp.get("/material-orders/<entity_id>")
@require(*ALL_ROLES)
def read_order(entity_id):
    return ok(domain.s_order(domain.get_order(entity_id)))


@bp.get("/material-orders")
@require(*ALL_ROLES)
def list_orders():
    work_plan_id = request.args.get("work_plan_id")
    condition_report_id = request.args.get("condition_report_id")
    status = request.args.get("status")
    if status is not None and status not in ORDER_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a declared member.")
    rows = store.ordered(list(store.orders.values()))
    if work_plan_id is not None:
        rows = [r for r in rows if r["work_plan_id"] == work_plan_id]
    if condition_report_id is not None:
        rows = [r for r in rows if r.get("condition_report_id") == condition_report_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, domain.s_order)


@bp.post("/material-orders/<entity_id>/submit")
@require("CrewLeader")
def submit_order(entity_id):
    order = domain.get_order(entity_id)
    if order["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT order may be submitted.")

    plan = domain.get_plan(order["work_plan_id"])
    segment = domain.plan_segment(plan)
    manager = domain.segment_manager(segment) if segment is not None else None

    if (order["category"] == "BRIDGE" and manager is not None
            and manager["requires_engineering_review"]
            and not order.get("engineering_review_ref")):
        fail("ERR_ENGINEERING_REVIEW_REQUIRED",
             "A structural sign-off reference is required.")
    if plan["status"] != "APPROVED":
        fail("ERR_WORK_PLAN_NOT_APPROVED", "The governing work plan is not APPROVED.")
    if plan["budget_posture"] == "OVER_COMMITTED":
        fail("ERR_PLAN_OVER_COMMITTED", "The work plan is over-committed.")

    order["status"] = "SUBMITTED"
    touch(order)
    return ok(domain.s_order(order))


@bp.post("/material-orders/<entity_id>/approve")
@require("StewardshipCoordinator")
def approve_order(entity_id):
    order = domain.get_order(entity_id)
    if order["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED order may be approved.")

    plan = domain.get_plan(order["work_plan_id"])
    if plan["status"] != "APPROVED":
        fail("ERR_WORK_PLAN_NOT_APPROVED", "The governing work plan is not APPROVED.")
    if plan["budget_posture"] == "OVER_COMMITTED":
        fail("ERR_PLAN_OVER_COMMITTED", "The work plan is over-committed.")

    order["status"] = "APPROVED"
    order["approved_by_user_id"] = actor()
    touch(order)
    return ok(domain.s_order(order))


@bp.post("/material-orders/<entity_id>/receive")
@require("CrewLeader")
def receive_order(entity_id):
    order = domain.get_order(entity_id)
    if order["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED order may be received.")

    plan = domain.get_plan(order["work_plan_id"])
    if plan["status"] != "APPROVED":
        fail("ERR_WORK_PLAN_NOT_APPROVED", "The governing work plan is not APPROVED.")

    order["status"] = "DELIVERED"
    order["delivered_at"] = store.now_iso()
    touch(order)
    _settle_plan(plan)
    return ok(domain.s_order(order))


@bp.post("/material-orders/<entity_id>/cancel")
@require("CrewLeader", "StewardshipCoordinator")
def cancel_order(entity_id):
    order = domain.get_order(entity_id)
    data = v.body()
    reason = v.req_str(data, "reason")

    if role() == "CrewLeader":
        allowed = ("DRAFT",)
    else:
        allowed = ("SUBMITTED", "APPROVED")
    if order["status"] not in allowed:
        fail("ERR_INVALID_STATE", "The order may not be cancelled from this state.")

    order["status"] = "CANCELLED"
    order["cancellation_reason"] = reason
    touch(order)
    plan = domain.get_plan(order["work_plan_id"])
    _settle_plan(plan)
    return ok(domain.s_order(order))
